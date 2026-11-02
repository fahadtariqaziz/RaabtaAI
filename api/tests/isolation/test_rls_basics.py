"""Row-Level Security + ORM tenant filter (step 1.3). Runs as the runtime role `raabta_app`."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import app.models
from app.core.config import Settings
from app.core.tenancy import (
    TenancyError,
    admin_session,
    scope_to_admin,
    scope_to_tenant,
    tenant_session,
)
from app.db.base import Base, TenantMixin
from app.db.rls import GLOBAL_TABLES
from app.db.session import make_sessionmaker
from app.models.core import Membership, User
from tests.support import Factory, Tenant

pytestmark = [pytest.mark.isolation, pytest.mark.integration]


@pytest.fixture
async def engine(it_settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(it_settings.database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
def two(factory: Factory) -> tuple[Tenant, Tenant]:
    return factory.tenant(), factory.tenant()


async def count(session: AsyncSession, table: str, inst: uuid.UUID) -> int:
    col = "id" if table == "institutions" else "institution_id"
    return int(
        await session.scalar(text(f"select count(*) from {table} where {col} = :i"), {"i": inst})  # noqa: S608
        or 0
    )


async def test_runtime_role_cannot_bypass_rls(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("select rolsuper, rolbypassrls from pg_roles where rolname = current_user")
            )
        ).one()
    assert tuple(row) == (False, False)


async def test_without_tenant_context_zero_rows(
    engine: AsyncEngine, two: tuple[Tenant, Tenant]
) -> None:
    a, _ = two
    async with make_sessionmaker(engine)() as session:
        for table in ("institutions", "memberships", "audit_log", "usage_daily"):
            assert await count(session, table, a.id) == 0, table
        assert await session.scalar(select(Membership).limit(1)) is None


async def test_tenant_sees_only_own_rows(engine: AsyncEngine, two: tuple[Tenant, Tenant]) -> None:
    a, b = two
    async with tenant_session(make_sessionmaker(engine), a.id) as session:
        assert await count(session, "institutions", a.id) == 1
        assert await count(session, "memberships", a.id) == 3
        assert await count(session, "institutions", b.id) == 0
        assert await count(session, "memberships", b.id) == 0
        # raw SQL bypasses the ORM layer — RLS alone must hide B
        total = await session.scalar(text("select count(distinct institution_id) from memberships"))
        assert total == 1


async def test_cross_tenant_insert_rejected(
    engine: AsyncEngine, two: tuple[Tenant, Tenant]
) -> None:
    a, b = two
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(make_sessionmaker(engine), a.id) as session:
            await session.execute(
                text(
                    "insert into audit_log (institution_id, action, entity) values (:i, 'x', 'y')"
                ),
                {"i": b.id},
            )


async def test_cross_tenant_update_and_delete_affect_nothing(
    engine: AsyncEngine, two: tuple[Tenant, Tenant]
) -> None:
    a, b = two
    async with tenant_session(make_sessionmaker(engine), a.id) as session:
        upd = await session.execute(
            text("update memberships set role = 'staff' where institution_id = :i"), {"i": b.id}
        )
        dele = await session.execute(
            text("delete from memberships where institution_id = :i"), {"i": b.id}
        )
        assert upd.rowcount == dele.rowcount == 0  # type: ignore[attr-defined]
        # moving an own row to another tenant violates WITH CHECK
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text("update memberships set institution_id = :b where institution_id = :a"),
                {"a": a.id, "b": b.id},
            )


async def test_admin_path_is_explicit_and_sees_all(
    engine: AsyncEngine, two: tuple[Tenant, Tenant]
) -> None:
    a, b = two
    async with admin_session(make_sessionmaker(engine)) as session:
        assert await count(session, "memberships", a.id) == 3
        assert await count(session, "memberships", b.id) == 3
    async with make_sessionmaker(engine)() as session, session.begin():
        await scope_to_tenant(session, a.id)
        with pytest.raises(TenancyError):
            await scope_to_admin(session)
        with pytest.raises(TenancyError):
            await scope_to_tenant(session, b.id)


async def test_orm_filter_is_a_second_layer(
    engine: AsyncEngine, two: tuple[Tenant, Tenant]
) -> None:
    """With RLS bypassed (admin role), the ORM filter alone still scopes queries and writes."""
    a, b = two
    async with make_sessionmaker(engine)() as session, session.begin():
        await scope_to_admin(session)
        session.info["institution_id"] = a.id  # simulate layer 2 only
        rows = (await session.scalars(select(Membership))).all()
        assert {m.institution_id for m in rows} == {a.id}
        session.add(Membership(institution_id=b.id, user_id=a.users["owner"], role="staff"))
        with pytest.raises(TenancyError):
            await session.flush()
        await session.rollback()


async def test_orm_stamps_institution_on_new_rows(
    engine: AsyncEngine, two: tuple[Tenant, Tenant]
) -> None:
    a, _ = two
    async with tenant_session(make_sessionmaker(engine), a.id) as session:
        user = User(email=f"stamp-{uuid.uuid4().hex[:6]}@raabta-test.pk", name="S")
        session.add(user)
        await session.flush()
        row = Membership(user_id=user.id, role="staff")  # no institution_id given
        session.add(row)
        await session.flush()
        assert row.institution_id == a.id


async def test_every_tenant_table_has_rls_policy(engine: AsyncEngine) -> None:
    """Lint: any table with institution_id (and every TenantMixin model) has RLS forced + policy."""
    assert app.models  # all models registered
    async with engine.connect() as conn:
        tenant_tables = set(
            (
                await conn.execute(
                    text(
                        "select table_name from information_schema.columns "
                        "where table_schema = 'public' and column_name = 'institution_id'"
                    )
                )
            ).scalars()
        ) | {"institutions"}
        rls = {
            r.relname: (r.relrowsecurity, r.relforcerowsecurity)
            for r in await conn.execute(
                text(
                    "select relname, relrowsecurity, relforcerowsecurity from pg_class "
                    "where relnamespace = 'public'::regnamespace and relkind = 'r'"
                )
            )
        }
        policies = set((await conn.execute(text("select tablename from pg_policies"))).scalars())
    mixin_tables = {
        str(getattr(m.local_table, "name", ""))
        for m in Base.registry.mappers
        if issubclass(m.class_, TenantMixin)
    }
    assert mixin_tables <= tenant_tables
    missing = {
        t for t in tenant_tables - GLOBAL_TABLES if rls.get(t) != (True, True) or t not in policies
    }
    assert not missing, f"tables without forced RLS + policy: {sorted(missing)}"
    unexpected_global = (tenant_tables & GLOBAL_TABLES) - {"webhook_events"}
    assert not unexpected_global, unexpected_global
