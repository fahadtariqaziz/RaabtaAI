"""`GET /api/v1/audit-log` and `GET /api/v1/usage` (admin+, own institution only)."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text

from app.api.deps import AdminCtx, SessionDep
from app.models.core import AuditLog, Institution, Membership, Plan, UsageDaily, User

router = APIRouter(tags=["audit", "usage"])
MAX_USAGE_DAYS = 366


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_email: str | None = None
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
    actor: uuid.UUID | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditOut]:
    """Newest first. Page with `before=<created_at of the last row>`. `action` is a prefix
    (e.g. `lead.` or `PATCH`)."""
    # Explicit filter on top of RLS (audit_log/usage_daily are not TenantMixin models).
    q = (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(AuditLog.institution_id == ctx.institution_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    if entity:
        q = q.where(AuditLog.entity == entity)
    if action:
        q = q.where(AuditLog.action.startswith(action))
    if actor:
        q = q.where(AuditLog.actor_user_id == actor)
    if since:
        q = q.where(AuditLog.created_at >= since)
    if before:
        q = q.where(AuditLog.created_at < before)
    out = []
    for row, email in (await session.execute(q)).all():
        item = AuditOut.model_validate(row)
        item.actor_email = email
        out.append(item)
    return out


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


class LimitBar(BaseModel):
    used: int | Decimal
    limit: int | Decimal | None


class UsageLimits(BaseModel):
    month: str
    plan: str | None
    conversations: LimitBar
    template_sends: LimitBar
    ai_cost_usd: LimitBar
    seats: LimitBar


_MONTH_SQL = text(
    """
SELECT
  (SELECT count(*) FROM conversations WHERE institution_id = :iid
     AND created_at >= (CAST(:d0 AS date)::timestamp AT TIME ZONE :tz)
     AND created_at < (CAST(:d1 AS date)::timestamp AT TIME ZONE :tz)) AS conversations,
  (SELECT coalesce(sum(cost_usd), 0) FROM llm_runs WHERE institution_id = :iid
     AND created_at >= (CAST(:d0 AS date)::timestamp AT TIME ZONE :tz)
     AND created_at < (CAST(:d1 AS date)::timestamp AT TIME ZONE :tz)) AS cost
"""
)
Month = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")]


@router.get("/usage/limits")
async def usage_limits(ctx: AdminCtx, session: SessionDep, month: Month = None) -> UsageLimits:
    """Month-to-date usage vs plan limits (plan limit bars). Live counts for conversations/AI
    cost (today is not rolled up yet); template sends from `usage_daily`."""
    inst = await session.get(Institution, ctx.institution_id)
    plan = await session.get(Plan, inst.plan_id) if inst and inst.plan_id else None
    first = date.fromisoformat(f"{month}-01") if month else date.today().replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    tz = inst.timezone if inst else "Asia/Karachi"
    params = {"iid": ctx.institution_id, "tz": tz, "d0": first, "d1": nxt}
    live = (await session.execute(_MONTH_SQL, params)).mappings().one()
    sends = await session.scalar(
        select(func.coalesce(func.sum(UsageDaily.template_sends), 0)).where(
            UsageDaily.institution_id == ctx.institution_id,
            UsageDaily.date >= first,
            UsageDaily.date < nxt,
        )
    )
    seats = await session.scalar(
        select(func.count()).select_from(Membership).where(Membership.status != "disabled")
    )

    def bar(used: int | Decimal, limit: int | Decimal | None) -> LimitBar:
        return LimitBar(used=used, limit=limit)

    return UsageLimits(
        month=first.strftime("%Y-%m"),
        plan=plan.name if plan else None,
        conversations=bar(live["conversations"], plan.monthly_conversations if plan else None),
        template_sends=bar(sends or 0, plan.monthly_template_sends if plan else None),
        ai_cost_usd=bar(Decimal(live["cost"]), plan.monthly_ai_budget_usd if plan else None),
        seats=bar(seats or 0, plan.seats if plan else None),
    )
