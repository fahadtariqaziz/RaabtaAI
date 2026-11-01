"""Process-wide connections (DB engine + session factory, Redis), created in the app lifespan."""

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import make_engine, make_sessionmaker


@dataclass
class Resources:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis

    @classmethod
    def from_settings(cls, settings: Settings) -> "Resources":
        engine = make_engine(settings.database_url)
        return cls(
            engine=engine,
            sessionmaker=make_sessionmaker(engine),
            redis=Redis.from_url(settings.redis_url),
        )

    async def close(self) -> None:
        await self.redis.aclose()
        await self.engine.dispose()
