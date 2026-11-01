"""arq worker entrypoint: `arq app.jobs.worker.WorkerSettings`.

Jobs and cron schedules are added in later steps (ingestion 2.8, follow-ups 6.7, reminders 7.3).
"""

import os
from typing import Any, ClassVar

from arq.connections import RedisSettings


async def ping(ctx: dict[str, Any]) -> str:
    """Health job used by verification scripts to prove the worker consumes the queue."""
    return "pong"


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:56379/0")
    )
