from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api.audit_usage import router as audit_usage_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.api.kb import router as kb_router
from app.api.members import router as members_router
from app.core.config import Settings, get_settings
from app.core.logging import RequestIdMiddleware, configure_logging
from app.core.resources import Resources


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()  # fails fast on missing/invalid env
    configure_logging(json=settings.env != "dev")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.resources = Resources.from_settings(settings)
        try:
            yield
        finally:
            await app.state.resources.close()

    app = FastAPI(title="RaabtaAI API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health_router)
    v1 = APIRouter(prefix="/api/v1")
    for router in (auth_router, members_router, audit_usage_router, kb_router, internal_router):
        v1.include_router(router)
    app.include_router(v1)
    return app


app = create_app()
