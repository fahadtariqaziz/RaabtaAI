"""Operator CLI: `uv run python -m app.cli <command>`.

seed [--institution all|<slug>] [--reset]   load demo institutions (idempotent)
seed-docs [--force]                         (re)build demo fee XLSX + prospectus DOCX
ingest-seeds [--institution all|<slug>] [--no-approve]
                                            run demo documents through the KB pipeline
"""

import argparse
import asyncio
import sys

from app.core.config import get_settings
from app.core.tenancy import admin_session
from app.db.session import make_engine, make_sessionmaker
from app.kb.blobstore import make_blobstore
from app.kb.embeddings import make_provider
from app.kb.ingest import IngestDeps
from app.llm.claude import ClaudeClient
from app.seeds.documents import ensure_documents
from app.seeds.ingest import ingest_seed_institution
from app.seeds.loader import seed_institution, seed_superadmin
from app.seeds.schema import load_seed, seed_dirs

DEV_DEMO_PASSWORD = "Raabta-demo-2027"  # noqa: S105 (dev/demo only; prod requires env)


def _demo_password() -> str:
    settings = get_settings()
    if settings.seed_demo_password is not None:
        return settings.seed_demo_password.get_secret_value()
    if settings.env == "prod":
        sys.exit("SEED_DEMO_PASSWORD must be set to seed in prod")
    return DEV_DEMO_PASSWORD


async def seed(target: str, reset: bool) -> int:
    dirs = seed_dirs()
    seeds = [(d, load_seed(d)) for d in dirs]
    if target != "all":
        seeds = [(d, s) for d, s in seeds if s.institution.slug == target]
        if not seeds:
            print(f"unknown institution {target!r}", file=sys.stderr)
            return 2
    password = _demo_password()
    engine = make_engine(get_settings().database_url)
    try:
        async with admin_session(make_sessionmaker(engine)) as session:
            await seed_superadmin(session, password)
            for directory, data in seeds:
                r = await seed_institution(session, data, directory, password=password, reset=reset)
                print(
                    f"seeded {r.slug}: users={r.users} contacts={r.contacts} leads={r.leads} "
                    f"slots={r.slots} docs={len(r.documents)}"
                )
    finally:
        await engine.dispose()
    return 0


async def ingest_seeds(target: str, approve: bool) -> int:
    settings = get_settings()
    seeds = [(d, load_seed(d)) for d in seed_dirs()]
    if target != "all":
        seeds = [(d, s) for d, s in seeds if s.institution.slug == target]
        if not seeds:
            print(f"unknown institution {target!r}", file=sys.stderr)
            return 2
    engine = make_engine(settings.database_url)
    needs_llm = settings.kb_facts_llm or settings.kb_vision_ocr
    deps = IngestDeps(
        sessionmaker=make_sessionmaker(engine),
        blobstore=make_blobstore(settings),
        settings=settings,
        provider=make_provider(settings),
        llm=ClaudeClient(settings.require("anthropic_api_key")) if needs_llm else None,
    )
    rc = 0
    try:
        for directory, data in seeds:
            r = await ingest_seed_institution(deps, data, directory, approve=approve)
            print(
                f"ingested {r.slug}: docs={r.documents} seed_facts={r.seed_facts} "
                f"approved={r.approved} (embeddings: {deps.provider.name})"
            )
            rc |= int(any(status != "ready" for status in r.documents.values()))
    finally:
        await engine.dispose()
    return rc


def seed_docs(force: bool) -> int:
    for directory in seed_dirs():
        for path in ensure_documents(load_seed(directory), directory, force=force):
            print(path.relative_to(directory.parent))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p_seed = sub.add_parser("seed", help="load demo institutions")
    p_seed.add_argument("--institution", default="all")
    p_seed.add_argument("--reset", action="store_true")
    p_docs = sub.add_parser("seed-docs", help="build demo documents")
    p_docs.add_argument("--force", action="store_true")
    p_ing = sub.add_parser("ingest-seeds", help="ingest demo documents into the KB")
    p_ing.add_argument("--institution", default="all")
    p_ing.add_argument("--no-approve", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "seed":
        return asyncio.run(seed(args.institution, args.reset))
    if args.command == "ingest-seeds":
        return asyncio.run(ingest_seeds(args.institution, not args.no_approve))
    return seed_docs(args.force)


if __name__ == "__main__":
    raise SystemExit(main())
