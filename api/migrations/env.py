"""Alembic env (async).

URL precedence: `-x url=...` (tests) > MIGRATIONS_DATABASE_URL env > Settings (.env).
Always migrate as the table-owner role, never as runtime `raabta_app` (it must not own tables or
RLS would be bypassed — see infra/db/init.sql).
"""

import asyncio
import os

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.db.base import Base

config = context.config
target_metadata = Base.metadata

# Library-managed tables (LangGraph checkpointer, created in 0003 via its own `setup()`).
EXTERNAL_TABLES = frozenset(
    {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
)


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    return not (type_ == "table" and name in EXTERNAL_TABLES)


def _url() -> str:
    x_url = context.get_x_argument(as_dictionary=True).get("url")
    if x_url:
        return x_url
    env_url = os.environ.get("MIGRATIONS_DATABASE_URL")
    if env_url:
        return env_url
    from app.core.config import get_settings

    settings = get_settings()
    return settings.migrations_database_url or settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
