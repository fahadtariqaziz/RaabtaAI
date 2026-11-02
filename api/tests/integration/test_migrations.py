"""Migrations round-trip + DB-level constraints. Needs IT_MIGRATIONS_URL pointing at an EMPTY,
disposable database (scripts/verify/p1_s1.sh recreates `raabta_test`)."""

import os
import subprocess
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

pytestmark = pytest.mark.integration

URL = os.environ.get("IT_MIGRATIONS_URL", "")
EXPECTED_TABLES = {
    "audit_log",
    "institutions",
    "memberships",
    "plans",
    "usage_daily",
    "users",
    "webhook_events",
    "contacts",
    "conversations",
    "messages",
    "llm_runs",
    "leads",
    "slots",
    "bookings",
    "followups",
    "checkpoints",
    "checkpoint_writes",
}


def alembic(*args: str) -> str:
    result = subprocess.run(  # noqa: S603 — fixed argv, test-only
        ["uv", "run", "alembic", "-x", f"url={URL}", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout + result.stderr


async def tables(conn: AsyncConnection) -> set[str]:
    rows = await conn.execute(text("select tablename from pg_tables where schemaname = 'public'"))
    return {r[0] for r in rows} - {"alembic_version"}


@pytest.fixture
async def conn() -> AsyncIterator[AsyncConnection]:
    if not URL:
        pytest.skip("IT_MIGRATIONS_URL not set")
    engine = create_async_engine(URL)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def test_upgrade_downgrade_roundtrip_and_no_drift(conn: AsyncConnection) -> None:
    alembic("upgrade", "head")
    assert await tables(conn) >= EXPECTED_TABLES
    assert "No new upgrade operations detected" in alembic("check")

    alembic("downgrade", "base")
    await conn.rollback()
    assert await tables(conn) == set()

    alembic("upgrade", "head")
    await conn.rollback()
    assert await tables(conn) >= EXPECTED_TABLES


async def test_extensions_installed(conn: AsyncConnection) -> None:
    alembic("upgrade", "head")
    rows = await conn.execute(text("select extname from pg_extension"))
    assert {"vector", "pg_trgm", "unaccent"} <= {r[0] for r in rows}


@pytest.mark.parametrize(
    ("sql", "constraint"),
    [
        (
            "insert into institutions (slug, name, type, city) values ('x', 'X', 'hospital', 'L')",
            "ck_institutions_type_valid",
        ),
        ("insert into users (email, name) values ('Fahad@X.com', 'F')", "ck_users_email_lowercase"),
    ],
)
async def test_db_constraints_reject_bad_rows(
    conn: AsyncConnection, sql: str, constraint: str
) -> None:
    alembic("upgrade", "head")
    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(text(sql))
    await conn.rollback()


async def test_membership_unique_per_institution_and_user(conn: AsyncConnection) -> None:
    alembic("upgrade", "head")
    inst = (
        await conn.execute(
            text(
                "insert into institutions (slug, name, type, city) "
                "values ('uq-test', 'U', 'school', 'Lahore') returning id"
            )
        )
    ).scalar_one()
    user = (
        await conn.execute(
            text("insert into users (email, name) values ('uq@test.pk', 'U') returning id")
        )
    ).scalar_one()
    insert = text(
        "insert into memberships (institution_id, user_id, role) values (:i, :u, 'staff')"
    )
    await conn.execute(insert, {"i": inst, "u": user})
    with pytest.raises(IntegrityError, match="uq_memberships_institution_id_user_id"):
        await conn.execute(insert, {"i": inst, "u": user})
    await conn.rollback()
