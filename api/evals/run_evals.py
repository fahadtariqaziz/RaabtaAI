"""Eval runner: `uv run python -m evals.run_evals --suite retrieval [options]`.

retrieval — runs the 60-question set against the ingested demo institutions (`make seed` +
`make ingest-seeds` first) using hybrid search; prints recall@k / MRR per language; exits 1 below
the PLAN §12 gate (recall@5 ≥ 0.90 overall, Roman Urdu ≥ 0.85). Uses DATABASE_URL and
EMBEDDING_PROVIDER from the environment/.env (fake = no spend; queries only for real providers).
"""

import argparse
import asyncio
import datetime as dt
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.tenancy import admin_session, tenant_session
from app.db.session import make_engine, make_sessionmaker
from app.kb.embeddings import EmbeddingProvider, InputType, make_provider
from app.kb.search import LEGS, dense_query_text, search
from app.models.core import Institution
from evals.graders.retrieval import RetrievalCase, RetrievalReport, first_hit_rank, load_cases

REPORTS = Path(__file__).resolve().parent / "reports"
GATE_ALL, GATE_RU = 0.90, 0.85


class PrecomputedQueries:
    """Wraps a provider: query vectors computed once in a batch, documents passed through."""

    def __init__(self, inner: EmbeddingProvider, cache: dict[str, list[float]]) -> None:
        self.inner, self.cache = inner, cache
        self.name, self.dim = inner.name, inner.dim

    @classmethod
    async def build(cls, inner: EmbeddingProvider, queries: list[str]) -> "PrecomputedQueries":
        texts = list(dict.fromkeys(dense_query_text(q) for q in queries))
        vectors = await inner.embed(texts, "query")
        return cls(inner, dict(zip(texts, vectors, strict=True)))

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        if input_type == "query" and all(t in self.cache for t in texts):
            return [self.cache[t] for t in texts]
        return await self.inner.embed(texts, input_type)


async def institution_ids(
    sessionmaker: async_sessionmaker[AsyncSession], slugs: set[str]
) -> dict[str, uuid.UUID]:
    async with admin_session(sessionmaker) as session:
        rows = await session.execute(
            select(Institution.slug, Institution.id).where(Institution.slug.in_(slugs))
        )
        return {r[0]: r[1] for r in rows.all()}


async def run_retrieval(
    sessionmaker: async_sessionmaker[AsyncSession],
    provider: EmbeddingProvider | None,
    cases: list[RetrievalCase],
    *,
    legs: tuple[str, ...] = LEGS,
    top_k: int = 5,
    label: str = "hybrid",
) -> RetrievalReport:
    ids = await institution_ids(sessionmaker, {c.institution for c in cases})
    missing = {c.institution for c in cases} - set(ids)
    if missing:
        raise SystemExit(f"institutions not found (run make seed + ingest-seeds): {missing}")
    if provider is not None:  # one batched call for all queries (rate-limited providers)
        provider = await PrecomputedQueries.build(provider, [c.query for c in cases])
    report = RetrievalReport(label=label)
    for case in cases:
        async with tenant_session(sessionmaker, ids[case.institution]) as session:
            hits = await search(
                session, ids[case.institution], [case.query], provider, top_k=top_k, legs=legs
            )
        report.ranks[case.id] = first_hit_rank([h.text for h in hits], case.gold)
        report.langs[case.id] = case.lang
    return report


def gate(report: RetrievalReport) -> list[str]:
    failures = []
    overall = report.metrics()["recall@5"]
    ru = report.metrics("roman_ur").get("recall@5", 1.0)
    if overall < GATE_ALL:
        failures.append(f"recall@5 {overall:.2f} < {GATE_ALL}")
    if ru < GATE_RU:
        failures.append(f"roman_ur recall@5 {ru:.2f} < {GATE_RU}")
    return failures


async def main_retrieval(args: argparse.Namespace) -> int:
    settings = get_settings()
    provider = make_provider(settings, args.provider)
    legs = tuple(args.legs.split(","))
    engine = make_engine(settings.database_url)
    try:
        report = await run_retrieval(
            make_sessionmaker(engine),
            provider,
            load_cases(),
            legs=legs,
            label=f"{provider.name} · legs={'+'.join(legs)}",
        )
    finally:
        await engine.dispose()
    print(report.markdown())
    misses = report.misses()
    if misses:
        print("misses@5:", ", ".join(misses))
    failures = gate(report)
    if args.report:
        REPORTS.mkdir(exist_ok=True)
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
        out = REPORTS / f"retrieval-{stamp}.json"
        out.write_text(
            json.dumps(
                {"label": report.label, "metrics": report.by_lang(), "misses": misses}, indent=1
            )
        )
        print(f"report: {out}")
    if failures and not args.no_gate:
        print("GATE FAILED:", "; ".join(failures))
        return 1
    print("gate:", "skipped" if args.no_gate else "passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run_evals")
    parser.add_argument("--suite", required=True, choices=["retrieval"])
    parser.add_argument("--provider", choices=["fake", "voyage", "bge_m3"], default=None)
    parser.add_argument("--legs", default=",".join(LEGS))
    parser.add_argument("--report", action="store_true", help="write evals/reports/*.json")
    parser.add_argument("--no-gate", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(main_retrieval(args))


if __name__ == "__main__":
    sys.exit(main())
