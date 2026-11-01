from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
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
    return app


app = create_app()
