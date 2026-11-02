"""Process-wide connections (DB engine + session factory, Redis/arq, blob store), created in the
app lifespan."""

from dataclasses import dataclass

from arq.connections import ArqRedis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import make_engine, make_sessionmaker
from app.kb.blobstore import BlobStore, make_blobstore


@dataclass
class Resources:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: ArqRedis  # plain Redis client + `enqueue_job` for the arq worker
    blobstore: BlobStore

    @classmethod
    def from_settings(cls, settings: Settings) -> "Resources":
        engine = make_engine(settings.database_url)
        return cls(
            engine=engine,
            sessionmaker=make_sessionmaker(engine),
            redis=ArqRedis.from_url(settings.redis_url),
            blobstore=make_blobstore(settings),
        )

    async def close(self) -> None:
        await self.redis.aclose()
        await self.engine.dispose()
