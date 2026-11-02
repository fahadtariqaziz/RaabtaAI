"""arq worker entrypoint: `arq app.jobs.worker.WorkerSettings`.

Jobs: `ping` (health), nightly `rollup_usage_job` (00:30 Asia/Karachi → yesterday's usage).
More jobs come with ingestion 2.8, follow-ups 6.7, reminders 7.3.
"""

import os
from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.tenancy import admin_session
from app.db.session import make_engine, make_sessionmaker
from app.services.usage import rollup_usage

PK_TZ = ZoneInfo("Asia/Karachi")


async def ping(ctx: dict[str, Any]) -> str:
    """Health job used by verification scripts to prove the worker consumes the queue."""
    return "pong"


async def startup(ctx: dict[str, Any]) -> None:
    engine = make_engine(get_settings().database_url)
    ctx["engine"] = engine
    ctx["sessionmaker"] = make_sessionmaker(engine)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


async def rollup_usage_job(ctx: dict[str, Any], day: str | None = None) -> int:
    """Roll up `day` (ISO date; default: yesterday in Pakistan time) for every institution."""
    target = date.fromisoformat(day) if day else datetime.now(PK_TZ).date() - timedelta(days=1)
    async with admin_session(ctx["sessionmaker"]) as session:
        return await rollup_usage(session, target)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping, rollup_usage_job]
    cron_jobs: ClassVar[list[Any]] = [
        cron(rollup_usage_job, hour={0}, minute={30}, run_at_startup=False)
    ]
    timezone = PK_TZ
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:56379/0")
    )
