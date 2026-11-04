"""arq worker entrypoint: `arq app.jobs.worker.WorkerSettings`.

Jobs: `ping` (health), nightly `rollup_usage_job` (00:30 Asia/Karachi → yesterday's usage),
`ingest_document_job` (KB pipeline, step 2.8), WhatsApp: `whatsapp_event_job` (one stored webhook
item, step 6.2.4), `deliver_message_job` (queued outbound row / retry, 6.3), cron
`dispatch_followups_job` (every minute, 6.7.1) and `daily_summary_job` (18:00 PKT, 6.7.2).
"""

import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from arq import Retry, cron
from arq.connections import RedisSettings

from app.agent.runtime import AgentRuntimeHolder
from app.channels.stt import make_stt
from app.channels.whatsapp.client import WhatsAppClient
from app.core.config import Settings, get_settings
from app.core.resources import Resources
from app.core.tenancy import admin_session
from app.db.session import make_engine, make_sessionmaker
from app.kb.blobstore import make_blobstore
from app.kb.embeddings import make_provider
from app.kb.ingest import IngestDeps, ingest_document
from app.llm.claude import ClaudeClient
from app.services.daily_summary import send_daily_summaries
from app.services.followups import dispatch_due
from app.services.usage import rollup_usage
from app.services.whatsapp import WhatsAppDeps, deliver_message, process_event

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

    ctx["resources"] = Resources.from_settings(settings)
    ctx["agent"] = AgentRuntimeHolder(settings, ctx["resources"])
    ctx["whatsapp"] = make_whatsapp_deps(settings, ctx["resources"], ctx["agent"])


def make_whatsapp_deps(
    settings: Settings, resources: Resources, agent: AgentRuntimeHolder
) -> WhatsAppDeps:
    stt_cache: list[Any] = []

    def stt() -> Any:  # built on first voice note (missing key → that note asks to type)
        if not stt_cache:
            stt_cache.append(make_stt(settings))
        return stt_cache[0]

    return WhatsAppDeps(
        sessionmaker=resources.sessionmaker,
        client=WhatsAppClient.from_settings(settings) if settings.meta_access_token else None,
        blobstore=resources.blobstore,
        redis=resources.redis,
        agent=agent.get,
        stt=stt,
        enqueue=resources.redis.enqueue_job,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    wa: WhatsAppDeps = ctx["whatsapp"]
    if wa.client is not None:
        await wa.client.aclose()
    await ctx["agent"].close()
    await ctx["resources"].close()
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


async def whatsapp_event_job(ctx: dict[str, Any], event_id: str) -> str:
    return await process_event(ctx["whatsapp"], uuid.UUID(event_id))


DELIVER_TRIES = 5


async def deliver_message_job(ctx: dict[str, Any], institution_id: str, message_id: str) -> str:
    """Deliver a queued outbound row (staff reply, booking note, Graph retry). Retryable Graph
    errors re-run this job with growing delays; the last try marks the row failed."""
    attempt = ctx.get("job_try", 1)
    status = await deliver_message(
        ctx["whatsapp"],
        uuid.UUID(institution_id),
        uuid.UUID(message_id),
        allow_retry=attempt < DELIVER_TRIES,
    )
    if status == "retry":
        raise Retry(defer=30 * attempt)
    return status


async def dispatch_followups_job(ctx: dict[str, Any]) -> dict[str, int]:
    lock = "followups:dispatch-lock"
    if not await ctx["redis"].set(lock, "1", nx=True, ex=300):
        return {"locked": 1}
    try:
        return await dispatch_due(ctx["whatsapp"])
    finally:
        await ctx["redis"].delete(lock)


async def daily_summary_job(ctx: dict[str, Any]) -> int:
    return await send_daily_summaries(ctx["whatsapp"])


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        rollup_usage_job,
        ingest_document_job,
        whatsapp_event_job,
        deliver_message_job,
        dispatch_followups_job,
        daily_summary_job,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(rollup_usage_job, hour={0}, minute={30}, run_at_startup=False),
        cron(dispatch_followups_job, second={0}, run_at_startup=False, unique=True),
        cron(daily_summary_job, hour={18}, minute={0}, run_at_startup=False, unique=True),
    ]
    timezone = PK_TZ
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:56379/0")
    )
