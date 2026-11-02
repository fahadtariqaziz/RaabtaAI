"""Audit trail (PLAN §10 G15): who changed what, with before/after snapshots.

Two layers:
- `audit(...)` — explicit, domain-level rows with before/after (members, takeovers, sends, …).
- `app.api.deps.audit_mutations` — router-level dependency for tenant routers: any successful
  POST/PUT/PATCH/DELETE that did not call `audit(...)` still gets a generic `"<METHOD> <route>"`
  row, written in the same transaction (an audit row exists iff the change was committed).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantContext
from app.models.core import AuditLog

MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_REDACT = frozenset({"password", "password_hash", "invite_token_hash", "token"})


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if k in _REDACT else _jsonable(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def snapshot(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: _jsonable(getattr(obj, f)) for f in fields}


async def audit(
    session: AsyncSession,
    *,
    institution_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity: str,
    entity_id: uuid.UUID | str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    request: Request | None = None,
) -> AuditLog:
    row = AuditLog(
        institution_id=institution_id,
        actor_user_id=actor_user_id,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_jsonable(before) if before is not None else None,
        after=_jsonable(after) if after is not None else None,
        ip=ip or (request.client.host if request and request.client else None),
    )
    session.add(row)
    if request is not None:
        request.state.audited = True
    return row


async def audit_ctx(
    session: AsyncSession,
    ctx: TenantContext,
    request: Request,
    *,
    action: str,
    entity: str,
    entity_id: uuid.UUID | str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """Tenant-route shorthand."""
    return await audit(
        session,
        institution_id=ctx.institution_id,
        actor_user_id=ctx.user_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before=before,
        after=after,
        request=request,
    )
