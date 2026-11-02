"""`GET /api/v1/audit-log` and `GET /api/v1/usage` (admin+, own institution only)."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import AdminCtx, SessionDep
from app.models.core import AuditLog, UsageDaily

router = APIRouter(tags=["audit", "usage"])
MAX_USAGE_DAYS = 366


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    entity: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    created_at: datetime


class UsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    date: date
    conversations: int
    messages_in: int
    messages_out: int
    template_sends: int
    tokens_in: int
    tokens_out: int
    llm_cost_usd: Decimal
    leads: int
    bookings: int
    fee_recovered_pkr: int


class UsageReport(BaseModel):
    days: list[UsageOut]
    totals: dict[str, int | Decimal]


@router.get("/audit-log")
async def audit_log(
    ctx: AdminCtx,
    session: SessionDep,
    entity: str | None = None,
    action: str | None = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditOut]:
    """Newest first. Page with `before=<created_at of the last row>`."""
    # Explicit filter on top of RLS (audit_log/usage_daily are not TenantMixin models).
    q = select(AuditLog).where(AuditLog.institution_id == ctx.institution_id)
    q = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    if entity:
        q = q.where(AuditLog.entity == entity)
    if action:
        q = q.where(AuditLog.action == action)
    if before:
        q = q.where(AuditLog.created_at < before)
    return [AuditOut.model_validate(r) for r in await session.scalars(q)]


@router.get("/usage")
async def usage(
    ctx: AdminCtx,
    session: SessionDep,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> UsageReport:
    """Daily usage rows in [from, to] (default: last 30 days) + totals."""
    end = date_to or date.today()
    start = date_from or end - timedelta(days=29)
    if start > end or (end - start).days >= MAX_USAGE_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid date range")
    rows = [
        UsageOut.model_validate(r)
        for r in await session.scalars(
            select(UsageDaily)
            .where(
                UsageDaily.institution_id == ctx.institution_id,
                UsageDaily.date >= start,
                UsageDaily.date <= end,
            )
            .order_by(UsageDaily.date)
        )
    ]
    totals: dict[str, int | Decimal] = {
        field: sum((getattr(r, field) for r in rows), Decimal(0) if field == "llm_cost_usd" else 0)
        for field in UsageOut.model_fields
        if field != "date"
    }
    return UsageReport(days=rows, totals=totals)
