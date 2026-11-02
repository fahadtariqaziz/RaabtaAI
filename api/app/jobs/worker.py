"""arq worker entrypoint: `arq app.jobs.worker.WorkerSettings`.

Jobs: `ping` (health), nightly `rollup_usage_job` (00:30 Asia/Karachi → yesterday's usage),
`ingest_document_job` (KB pipeline, step 2.8). More jobs come with follow-ups 6.7, reminders 7.3.
"""

import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.tenancy import admin_session
from app.db.session import make_engine, make_sessionmaker
from app.kb.blobstore import make_blobstore
from app.kb.embeddings import make_provider
from app.kb.ingest import IngestDeps, ingest_document
from app.llm.claude import ClaudeClient
from app.services.usage import rollup_usage

PK_TZ = ZoneInfo("Asia/Karachi")


async def ping(ctx: dict[str, Any]) -> str:
    """Health job used by verification scripts to prove the worker consumes the queue."""
    return "pong"


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    ctx["engine"] = engine
    ctx["sessionmaker"] = make_sessionmaker(engine)
    needs_llm = settings.kb_facts_llm or settings.kb_vision_ocr
    ctx["ingest"] = IngestDeps(
        sessionmaker=ctx["sessionmaker"],
        blobstore=make_blobstore(settings),
        settings=settings,
        provider=make_provider(settings),
        llm=ClaudeClient(settings.require("anthropic_api_key")) if needs_llm else None,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


async def rollup_usage_job(ctx: dict[str, Any], day: str | None = None) -> int:
    """Roll up `day` (ISO date; default: yesterday in Pakistan time) for every institution."""
    target = date.fromisoformat(day) if day else datetime.now(PK_TZ).date() - timedelta(days=1)
    async with admin_session(ctx["sessionmaker"]) as session:
        return await rollup_usage(session, target)


INGEST_LOCK_SECONDS = 1800


async def ingest_document_job(ctx: dict[str, Any], institution_id: str, document_id: str) -> str:
    """Run/resume the KB pipeline for one document. A Redis lock keeps one run per document."""
    lock = f"kb:ingest-lock:{document_id}"
    if not await ctx["redis"].set(lock, "1", nx=True, ex=INGEST_LOCK_SECONDS):
        return "locked"
    try:
        return await ingest_document(
            ctx["ingest"], uuid.UUID(institution_id), uuid.UUID(document_id)
        )
    finally:
        await ctx["redis"].delete(lock)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping, rollup_usage_job, ingest_document_job]
    cron_jobs: ClassVar[list[Any]] = [
        cron(rollup_usage_job, hour={0}, minute={30}, run_at_startup=False)
    ]
    timezone = PK_TZ
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:56379/0")
    )
