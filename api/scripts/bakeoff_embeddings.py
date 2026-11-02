"""Embedding bake-off (step 2.4.4, D-01): re-embed the ingested demo institutions with each
provider and run the 60-question retrieval set twice — dense-only and full hybrid — reporting
recall@k / MRR per language. Writes `evals/reports/bakeoff-<stamp>.md`.

    uv run python -m scripts.bakeoff_embeddings --providers fake,voyage [--subset 10]

Spends tokens for real providers (Voyage: ~100 chunk embeddings + 60 queries per run — cents).
Leaves chunks embedded with the LAST provider listed; re-run `--providers <chosen>` at the end.
"""

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.tenancy import admin_session
from app.db.session import make_engine, make_sessionmaker
from app.kb.blobstore import make_blobstore
from app.kb.embeddings import make_provider
from app.kb.ingest import IngestDeps, reembed_all
from app.models.core import Institution
from evals.graders.retrieval import load_cases
from evals.run_evals import run_retrieval

REPORTS = Path(__file__).resolve().parents[1] / "evals" / "reports"


async def bakeoff(providers: list[str], subset: int | None) -> int:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sm = make_sessionmaker(engine)
    cases = load_cases()
    if subset:  # balanced subset: first N/3 per language
        per = max(1, subset // 3)
        cases = [
            case
            for lang in ("en", "ur", "roman_ur")
            for case in [c for c in cases if c.lang == lang][:per]
        ]
    sections = [
        f"# Embedding bake-off — {dt.date.today().isoformat()}\n",
        f"Cases: {len(cases)} · corpus: demo institutions (small; recall@1/MRR most informative)\n",
    ]
    try:
        async with admin_session(sm) as session:
            slugs = {c.institution for c in cases}
            inst_ids = list(
                await session.scalars(select(Institution.id).where(Institution.slug.in_(slugs)))
            )
        for name in providers:
            provider = make_provider(settings, name)
            deps = IngestDeps(sm, make_blobstore(settings), settings, provider)
            for inst in inst_ids:
                await reembed_all(deps, inst)
            dense = await run_retrieval(
                sm, provider, cases, legs=("vector",), label=f"{provider.name} · dense only"
            )
            hybrid = await run_retrieval(sm, provider, cases, label=f"{provider.name} · hybrid")
            sections += [dense.markdown(), hybrid.markdown()]
            usage = getattr(provider, "total_tokens", None)
            if usage is not None:
                sections.append(f"_{provider.name} tokens used: {usage}_\n")
            print(dense.markdown(), hybrid.markdown(), sep="\n")
    finally:
        await engine.dispose()
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"bakeoff-{dt.datetime.now(dt.UTC):%Y%m%d-%H%M%S}.md"
    out.write_text("\n".join(sections), encoding="utf-8")
    print(f"report: {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", default="fake,voyage")
    parser.add_argument("--subset", type=int, default=None, help="e.g. 10 → ~3 per language")
    args = parser.parse_args()
    return asyncio.run(bakeoff(args.providers.split(","), args.subset))


if __name__ == "__main__":
    sys.exit(main())
