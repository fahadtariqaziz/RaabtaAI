import asyncio

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.core.resources import Resources

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_S = 2.0


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe: the process is up. Does not touch dependencies."""
    return {"status": "ok"}


async def _check_db(res: Resources) -> None:
    async with res.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis(res: Resources) -> None:
    await res.redis.ping()


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, object]:
    """Readiness probe: database and Redis reachable. 503 if any check fails."""
    res: Resources = request.app.state.resources
    checks: dict[str, str] = {}
    for name, fn in (("database", _check_db), ("redis", _check_redis)):
        try:
            await asyncio.wait_for(fn(res), CHECK_TIMEOUT_S)
            checks[name] = "ok"
        except Exception as exc:  # report, don't crash the probe
            checks[name] = f"error: {type(exc).__name__}"
    ready = all(v == "ok" for v in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ready else "unavailable", "checks": checks}
