"""Process-wide connections (DB engine, Redis), created in the app lifespan."""

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings


@dataclass
class Resources:
    engine: AsyncEngine
    redis: Redis

    @classmethod
    def from_settings(cls, settings: Settings) -> "Resources":
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        redis = Redis.from_url(settings.redis_url)
        return cls(engine=engine, redis=redis)

    async def close(self) -> None:
        await self.redis.aclose()
        await self.engine.dispose()
