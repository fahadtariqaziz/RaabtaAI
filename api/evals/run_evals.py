"""Eval runner: `uv run python -m evals.run_evals --suite <suite> [--mode live|record|replay]`.

Suites (PLAN §12): retrieval · router · guardrails · tone · admissions_{school,college,university}
(`--suite agent` = all LLM suites). `--validate` checks datasets only (no LLM, no DB).
- router / tone: classifier nodes only (no DB). Request hashes are deterministic → `--mode
  replay` serves cassettes in CI (`evals-smoke`).
- guardrails / admissions_*: full inbound graph via `run_inbound` against DATABASE_URL (seed +
  ingest-seeds first; use the disposable test DB), fixed clock EVAL_NOW, in-memory checkpointer,
  fresh contact per case; admissions replies are scored by the Opus judge unless `--no-judge`.
- `--mode live` spends tokens (needs ANTHROPIC_API_KEY + approval); `--mode record` = live +
  write cassettes under evals/cassettes/<node>/.
Reports: evals/reports/<suite>-<stamp>.{json,md} (MD = PR comment body). Exit 1 if a gate fails.

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
from dataclasses import asdict
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.graph import (
    AgentDeps,
    build_graph,
    cached_system,
    finalize_route,
    router_user_content,
)
from app.agent.inbound import InboundEvent, run_inbound
from app.agent.schemas import RouteDecision
from app.agent.skills_loader import available_for_router
from app.agent.tone import check_tone
from app.agent.tools import build_registry
from app.core.config import get_settings
from app.core.tenancy import admin_session, tenant_session
from app.db.session import make_engine, make_sessionmaker
from app.kb.embeddings import EmbeddingProvider, InputType, make_provider
from app.kb.search import LEGS, dense_query_text, search
from app.llm.base import LLMProvider
from app.llm.claude import CASSETTE_DIR, CassetteMissingError, ClaudeClient
from app.models.core import Institution
from app.seeds.schema import load_seed, seed_dirs
from evals.graders.agent import (
    AGENT_SUITES,
    Graded,
    JudgeVerdict,
    grade_admissions,
    grade_guardrail,
    grade_router,
    grade_tone,
    load_suite,
    metrics,
    report_md,
    validate_suite,
)
from evals.graders.agent import (
    gate as agent_gate,
)
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


EVAL_NOW = dt.datetime(2026, 11, 3, 5, 0, tzinfo=dt.UTC)  # Tue 10:00 PKT (stable cassettes)
LLM_SUITES = ("router", "tone", "guardrails", *AGENT_SUITES)


def seed_amounts() -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for d in seed_dirs():
        seed = load_seed(d)
        amounts = {f.amount_pkr for f in seed.facts.fee_items}
        amounts |= {r.monthly_pkr for r in seed.facts.transport_routes}
        out[seed.institution.slug] = amounts
    return out


def make_llm(mode: str) -> LLMProvider:
    settings = get_settings()
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    if mode != "replay" and not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set (live/record runs spend tokens)")
    return ClaudeClient(key, mode=mode)  # type: ignore[arg-type]


async def run_router(llm: LLMProvider, cases: list[dict[str, Any]]) -> list[Graded]:
    out: list[Graded] = []
    for case in cases:
        skills = available_for_router(case["institution_type"])
        res = await llm.parse(
            "router",
            system=cached_system("router"),
            messages=[
                {
                    "role": "user",
                    "content": router_user_content(
                        case["institution_type"], skills, "", "", case["message"]
                    ),
                }
            ],
            output_format=RouteDecision,
        )
        g = grade_router(case, finalize_route(res.output, skills).model_dump())
        g.cost_usd = float(res.cost_usd)
        out.append(g)
    return out


async def run_tone(llm: LLMProvider, cases: list[dict[str, Any]]) -> list[Graded]:
    out: list[Graded] = []
    for case in cases:
        verdict, record = await check_tone(llm, case["text"])
        g = grade_tone(case, verdict.model_dump())
        g.cost_usd = float(record.get("cost_usd") or 0)
        out.append(g)
    return out


def judge_content(case: dict[str, Any], turn: dict[str, Any]) -> str:
    sources = "\n".join(
        f'<source id="{s["id"]}">{s["text"][:1500]}</source>' for s in turn.get("sources", [])
    )
    expected = json.dumps(case["expect"].get("must_include_facts", []), ensure_ascii=False)
    return (
        f"<message>\n{case['message']}\n</message>\n"
        f"<expected_language>{case['expect']['language']}</expected_language>\n"
        f"<expected_facts>{expected}</expected_facts>\n"
        f"<sources>\n{sources or '(none)'}\n</sources>\n"
        f"<reply>\n{turn.get('reply') or ''}\n</reply>"
    )


async def run_agent_cases(
    suite: str,
    cases: list[dict[str, Any]],
    llm: LLMProvider,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    embedder: EmbeddingProvider | None,
    judge: LLMProvider | None,
    stamp: str,
) -> list[Graded]:
    """Each case = one fresh contact through the real graph (tools hit the seeded DB)."""
    ids = await institution_ids(sessionmaker, {c["institution"] for c in cases})
    missing = {c["institution"] for c in cases} - set(ids)
    if missing:
        raise SystemExit(f"institutions not found (run make seed + ingest-seeds): {missing}")
    deps = AgentDeps(
        sessionmaker=sessionmaker, llm=llm, registry=build_registry(), embedder=embedder
    )
    graph = build_graph(deps, InMemorySaver())
    out: list[Graded] = []
    for case in cases:
        result = await run_inbound(
            deps,
            graph,
            InboundEvent(
                institution_id=ids[case["institution"]],
                channel=case.get("channel", "widget"),
                text=case["message"],
                widget_visitor_id=f"eval-{case['id']}-{stamp}"[:64],
                now=EVAL_NOW,
            ),
        )
        turn = asdict(result)
        cost = float(result.cost_usd)
        if suite == "guardrails":
            g = grade_guardrail(case, turn)
        else:
            verdict = None
            if judge is not None and result.reply:
                res = await judge.parse(
                    "eval_judge",
                    system=cached_system("judge_admissions"),
                    messages=[{"role": "user", "content": judge_content(case, turn)}],
                    output_format=JudgeVerdict,
                )
                verdict = res.output.model_dump()
                cost += float(res.cost_usd)
            g = grade_admissions(case, turn, verdict)
        g.cost_usd = cost
        out.append(g)
    return out


def mark_recorded(suite: str, cases: int) -> None:
    """`evals/cassettes/suites/<suite>.json` = this suite was fully recorded (CI replays it)."""
    path = CASSETTE_DIR / "suites" / f"{suite}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    path.write_text(json.dumps({"suite": suite, "cases": cases, "recorded_at": stamp}) + "\n")


def write_report(suite: str, m: dict[str, Any], results: list[Graded], failures: list[str]) -> Path:
    REPORTS.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    base = REPORTS / f"{suite}-{stamp}"
    payload = {"suite": suite, "metrics": m, "gate_failures": failures,
               "results": [asdict(r) for r in results]}  # fmt: skip
    base.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str)
    )
    base.with_suffix(".md").write_text(report_md(suite, m, results, failures) + "\n")
    return base.with_suffix(".md")


async def main_llm(args: argparse.Namespace) -> int:
    suites = list(LLM_SUITES) if args.suite == "agent" else [args.suite]
    if args.validate:
        amounts = seed_amounts()
        problems = [p for s in suites for p in validate_suite(s, amounts)]
        for p in problems:
            print("✘", p)
        print(f"validated {', '.join(suites)}: {'OK' if not problems else 'FAILED'}")
        return 1 if problems else 0
    llm = make_llm(args.mode)
    judge = None if args.no_judge else llm
    settings = get_settings()
    engine = make_engine(settings.database_url)
    stamp = dt.datetime.now(dt.UTC).strftime("%H%M%S")
    rc = 0
    try:
        for suite in suites:
            cases = load_suite(suite)[: args.limit or None]
            try:
                if suite == "router":
                    results = await run_router(llm, cases)
                elif suite == "tone":
                    results = await run_tone(llm, cases)
                else:
                    results = await run_agent_cases(
                        suite,
                        cases,
                        llm,
                        make_sessionmaker(engine),
                        embedder=make_provider(settings, args.provider),
                        judge=judge,
                        stamp=stamp,
                    )
            except CassetteMissingError as exc:
                print(f"{suite}: no cassette — record first with --mode record ({exc})")
                rc = 1
                continue
            if args.mode == "record" and not args.limit:
                mark_recorded(suite, len(results))
            m = metrics(suite, results)
            failures = agent_gate(suite, m)
            print(report_md(suite, m, results, failures))
            if args.report:
                print("report:", write_report(suite, m, results, failures))
            if failures and not args.no_gate:
                rc = 1
    finally:
        await engine.dispose()
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run_evals")
    parser.add_argument("--suite", required=True, choices=["retrieval", *LLM_SUITES, "agent"])
    parser.add_argument("--mode", choices=["live", "record", "replay"], default="replay")
    parser.add_argument("--validate", action="store_true", help="datasets only (no LLM/DB)")
    parser.add_argument("--limit", type=int, default=0, help="first N cases per suite")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--provider", choices=["fake", "voyage", "bge_m3"], default=None)
    parser.add_argument("--legs", default=",".join(LEGS))
    parser.add_argument("--report", action="store_true", help="write evals/reports/*")
    parser.add_argument("--no-gate", action="store_true")
    args = parser.parse_args(argv)
    if args.suite == "retrieval":
        return asyncio.run(main_retrieval(args))
    return asyncio.run(main_llm(args))


if __name__ == "__main__":
    sys.exit(main())
