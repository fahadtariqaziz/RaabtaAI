"""Tenant context for DB sessions (PLAN §18).

Layer 1 — Postgres RLS: every tenant table has a policy
`institution_id = app_current_institution()` (reads the transaction-local GUC
`app.institution_id`). The runtime login role (`raabta_app`) is neither owner nor BYPASSRLS, so a
session that never set the GUC sees zero tenant rows.

Layer 2 — ORM: when `session.info["institution_id"]` is set, every ORM SELECT/UPDATE/DELETE on a
`TenantMixin` model gets `institution_id = :id` added, and new tenant objects are stamped with (or
checked against) that id on flush.

Two explicit modes per transaction:
- `scope_to_tenant(session, id)` → `SET LOCAL ROLE app_tenant` + GUC + ORM filter.
- `scope_to_admin(session)`      → `SET LOCAL ROLE app_admin` (BYPASSRLS). Only for auth lookups
  across institutions, superadmin routes, seeds and platform jobs. Grep-able on purpose.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.db.base import TenantMixin

TENANT_ROLE = "app_tenant"
ADMIN_ROLE = "app_admin"
_INFO_KEY = "institution_id"
_MODE_KEY = "tenancy_mode"


class TenancyError(RuntimeError):
    """Session used in the wrong tenancy mode or a row crossed a tenant boundary."""


@dataclass(frozen=True)
class TenantContext:
    """Resolved per request after membership check. Tools/services receive this, never raw ids
    from a model or client body."""

    institution_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    membership_id: uuid.UUID | None  # None = superadmin impersonation (step 5.9)


async def scope_to_tenant(session: AsyncSession, institution_id: uuid.UUID) -> None:
    mode = session.info.get(_MODE_KEY)
    if mode == "admin" or (mode == "tenant" and session.info.get(_INFO_KEY) != institution_id):
        raise TenancyError("session already scoped differently in this transaction")
    await session.execute(text(f"SET LOCAL ROLE {TENANT_ROLE}"))
    await session.execute(
        text("SELECT set_config('app.institution_id', :id, true)"), {"id": str(institution_id)}
    )
    session.info[_MODE_KEY] = "tenant"
    session.info[_INFO_KEY] = institution_id


async def scope_to_admin(session: AsyncSession) -> None:
    if session.info.get(_MODE_KEY) == "tenant":
        raise TenancyError("tenant-scoped session cannot be elevated to admin")
    await session.execute(text(f"SET LOCAL ROLE {ADMIN_ROLE}"))
    session.info[_MODE_KEY] = "admin"


@asynccontextmanager
async def tenant_session(
    sessionmaker: async_sessionmaker[AsyncSession], institution_id: uuid.UUID
) -> AsyncIterator[AsyncSession]:
    """Worker/job helper: one transaction scoped to `institution_id` (committed on success)."""
    async with sessionmaker() as session, session.begin():
        await scope_to_tenant(session, institution_id)
        yield session


@asynccontextmanager
async def admin_session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Platform helper (seeds, superadmin, cross-tenant jobs): RLS bypassed explicitly."""
    async with sessionmaker() as session, session.begin():
        await scope_to_admin(session)
        yield session


@event.listens_for(Session, "after_transaction_end")
def _reset_scope(session: Session, transaction: Any) -> None:
    """`SET LOCAL` ends with the outermost transaction — so does the ORM-side scope."""
    if transaction.parent is None:
        session.info.pop(_MODE_KEY, None)
        session.info.pop(_INFO_KEY, None)


@event.listens_for(Session, "do_orm_execute")
def _add_tenant_filter(state: ORMExecuteState) -> None:
    institution_id = state.session.info.get(_INFO_KEY)
    if institution_id is None or state.is_column_load or state.is_relationship_load:
        return
    if state.is_select or state.is_update or state.is_delete:
        state.statement = state.statement.options(
            with_loader_criteria(
                TenantMixin,
                lambda cls: cls.institution_id == institution_id,
                include_aliases=True,
            )
        )


@event.listens_for(Session, "before_flush")
def _stamp_tenant(session: Session, _ctx: Any, _instances: Any) -> None:
    institution_id = session.info.get(_INFO_KEY)
    if institution_id is None:
        return
    for obj in session.new:
        if isinstance(obj, TenantMixin):
            current = obj.institution_id
            if current is None:
                obj.institution_id = institution_id
            elif current != institution_id:
                raise TenancyError("refusing to write a row for another institution")
