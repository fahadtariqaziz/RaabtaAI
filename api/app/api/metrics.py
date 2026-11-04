"""`/api/v1/metrics/*` — overview dashboard (PLAN §14 Metrics, §17; step 5.3). Staff+.

Computed live from source tables (RLS-scoped, plus an explicit institution filter) with days
bucketed in the institution's timezone — `usage_daily` is the nightly rollup for billing; the
dashboard must also show today. KB-playground sandbox contacts are excluded. Fee figures stay
null until the fee module (Phase 7)."""

import datetime as dt
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, StaffCtx
from app.core.tenancy import TenantContext
from app.models.core import Institution

router = APIRouter(prefix="/metrics", tags=["metrics"])
Range = Literal["7d", "30d", "90d"]
DAYS = {"7d": 7, "30d": 30, "90d": 90}
FUNNEL = ("new", "contacted", "visit_booked", "applied", "admitted")


class Kpis(BaseModel):
    conversations: int
    messages_in: int
    messages_out: int
    leads: int
    visits_booked: int
    ai_resolved: int
    handed_off: int
    median_first_response_s: float | None
    median_staff_response_s: float | None
    ai_cost_usd: Decimal
    fee_recovered_pkr: int | None = None
    fee_outstanding_pkr: int | None = None


class TrendPoint(BaseModel):
    date: dt.date
    conversations: int
    leads: int
    messages_in: int


class AttentionItem(BaseModel):
    kind: str  # flagged | human_waiting | facts_pending | documents_failed
    count: int
    conversation_ids: list[str] = []


class Overview(BaseModel):
    range: str
    date_from: dt.date
    date_to: dt.date
    timezone: str
    kpis: Kpis
    previous: Kpis | None
    trend: list[TrendPoint]
    channels: dict[str, int]
    funnel: list[dict[str, Any]]
    attention: list[AttentionItem]


async def _window(
    session: AsyncSession, ctx: TenantContext, days: int
) -> tuple[str, dt.date, dt.date]:
    inst = await session.get(Institution, ctx.institution_id)
    tz = inst.timezone if inst else "Asia/Karachi"
    today = (
        await session.execute(text("SELECT (now() AT TIME ZONE :tz)::date"), {"tz": tz})
    ).scalar_one()
    return tz, today - dt.timedelta(days=days - 1), today


_KPI_SQL = text(
    """
WITH w AS (SELECT (CAST(:d0 AS date)::timestamp AT TIME ZONE :tz) t0,
                  ((CAST(:d1 AS date) + 1)::timestamp AT TIME ZONE :tz) t1),
conv AS (
  SELECT c.id, c.mode,
         EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND m.sender = 'staff'
                 AND m.type <> 'note') AS staff_replied
  FROM conversations c JOIN contacts ct ON ct.id = c.contact_id, w
  WHERE c.institution_id = :iid AND c.created_at >= w.t0 AND c.created_at < w.t1
    AND coalesce(ct.widget_visitor_id, '') NOT LIKE 'sandbox-%'
),
msg AS (
  SELECT m.direction, m.sender, m.type FROM messages m
  JOIN conversations c ON c.id = m.conversation_id JOIN contacts ct ON ct.id = c.contact_id, w
  WHERE m.institution_id = :iid AND m.created_at >= w.t0 AND m.created_at < w.t1
    AND coalesce(ct.widget_visitor_id, '') NOT LIKE 'sandbox-%'
),
resp AS (
  SELECT i.created_at AS t_in,
         (SELECT o.created_at FROM messages o WHERE o.conversation_id = i.conversation_id
            AND o.direction = 'out' AND o.type <> 'note' AND o.seq > i.seq
          ORDER BY o.seq LIMIT 1) AS t_out,
         (SELECT o.sender FROM messages o WHERE o.conversation_id = i.conversation_id
            AND o.direction = 'out' AND o.type <> 'note' AND o.seq > i.seq
          ORDER BY o.seq LIMIT 1) AS out_sender
  FROM messages i JOIN conversations c ON c.id = i.conversation_id
  JOIN contacts ct ON ct.id = c.contact_id, w
  WHERE i.institution_id = :iid AND i.direction = 'in' AND i.created_at >= w.t0
    AND i.created_at < w.t1
    AND coalesce(ct.widget_visitor_id, '') NOT LIKE 'sandbox-%'
)
SELECT
  (SELECT count(*) FROM conv) AS conversations,
  (SELECT count(*) FROM msg WHERE direction = 'in') AS messages_in,
  (SELECT count(*) FROM msg WHERE direction = 'out' AND sender <> 'system' AND type <> 'note')
    AS messages_out,
  (SELECT count(*) FROM leads l, w WHERE l.institution_id = :iid AND l.created_at >= w.t0
     AND l.created_at < w.t1) AS leads,
  (SELECT count(*) FROM bookings b, w WHERE b.institution_id = :iid AND b.created_at >= w.t0
     AND b.created_at < w.t1) AS visits_booked,
  (SELECT count(*) FROM conv WHERE mode = 'ai' AND NOT staff_replied) AS ai_resolved,
  (SELECT count(*) FROM conv WHERE mode = 'human' OR staff_replied) AS handed_off,
  (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM t_out - t_in))
     FROM resp WHERE t_out IS NOT NULL) AS median_first_response_s,
  (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM t_out - t_in))
     FROM resp WHERE t_out IS NOT NULL AND out_sender = 'staff') AS median_staff_response_s,
  (SELECT coalesce(sum(r.cost_usd), 0) FROM llm_runs r, w WHERE r.institution_id = :iid
     AND r.created_at >= w.t0 AND r.created_at < w.t1) AS ai_cost_usd
"""
)

_TREND_SQL = text(
    """
WITH days AS (SELECT generate_series(CAST(:d0 AS date), CAST(:d1 AS date), '1 day')::date d)
SELECT days.d AS date,
  (SELECT count(*) FROM conversations c JOIN contacts ct ON ct.id = c.contact_id
    WHERE c.institution_id = :iid AND (c.created_at AT TIME ZONE :tz)::date = days.d
    AND coalesce(ct.widget_visitor_id, '') NOT LIKE 'sandbox-%') AS conversations,
  (SELECT count(*) FROM leads l WHERE l.institution_id = :iid
    AND (l.created_at AT TIME ZONE :tz)::date = days.d) AS leads,
  (SELECT count(*) FROM messages m WHERE m.institution_id = :iid AND m.direction = 'in'
    AND (m.created_at AT TIME ZONE :tz)::date = days.d) AS messages_in
FROM days ORDER BY days.d
"""
)


async def _kpis(session: AsyncSession, params: dict[str, Any]) -> Kpis:
    row = (await session.execute(_KPI_SQL, params)).mappings().one()
    data = dict(row)
    for key in ("median_first_response_s", "median_staff_response_s"):
        if data[key] is not None:
            data[key] = round(float(data[key]), 1)
    return Kpis(**data)


@router.get("/overview")
async def overview(ctx: StaffCtx, session: SessionDep, range: Range = "30d") -> Overview:
    days = DAYS[range]
    tz, d0, d1 = await _window(session, ctx, days)
    params = {"iid": ctx.institution_id, "tz": tz, "d0": d0, "d1": d1}
    kpis = await _kpis(session, params)
    prev = await _kpis(
        session,
        {**params, "d0": d0 - dt.timedelta(days=days), "d1": d0 - dt.timedelta(days=1)},
    )
    trend = [TrendPoint(**r) for r in (await session.execute(_TREND_SQL, params)).mappings()]
    channels = {
        r.channel: r.n
        for r in await session.execute(
            text(
                """SELECT c.channel, count(*) n FROM conversations c
                JOIN contacts ct ON ct.id = c.contact_id
                WHERE c.institution_id = :iid
    AND coalesce(ct.widget_visitor_id, '') NOT LIKE 'sandbox-%'
                AND c.created_at >= (CAST(:d0 AS date)::timestamp AT TIME ZONE :tz)
                GROUP BY 1 ORDER BY 1"""
            ),
            params,
        )
    }
    return Overview(
        range=range,
        date_from=d0,
        date_to=d1,
        timezone=tz,
        kpis=kpis,
        previous=prev,
        trend=trend,
        channels=channels,
        funnel=await _funnel(session, ctx),
        attention=await _attention(session, ctx),
    )


async def _funnel(session: AsyncSession, ctx: TenantContext) -> list[dict[str, Any]]:
    """Cumulative stage counts: a lead at `applied` has passed new/contacted/visit_booked."""
    rows = await session.execute(
        text("SELECT status, count(*) n FROM leads WHERE institution_id = :iid GROUP BY 1"),
        {"iid": ctx.institution_id},
    )
    counts = {r.status: r.n for r in rows}
    out = []
    for i, stage in enumerate(FUNNEL):
        out.append({"stage": stage, "count": sum(counts.get(s, 0) for s in FUNNEL[i:])})
    out.append({"stage": "lost", "count": counts.get("lost", 0)})
    return out


@router.get("/funnel")
async def funnel(ctx: StaffCtx, session: SessionDep) -> list[dict[str, Any]]:
    return await _funnel(session, ctx)


async def _attention(session: AsyncSession, ctx: TenantContext) -> list[AttentionItem]:
    iid = {"iid": ctx.institution_id}
    flagged = (
        (
            await session.execute(
                text(
                    """SELECT id FROM conversations WHERE institution_id = :iid AND flagged
                AND status <> 'closed' ORDER BY updated_at DESC LIMIT 20"""
                ),
                iid,
            )
        )
        .scalars()
        .all()
    )
    waiting = (
        (
            await session.execute(
                text(
                    """SELECT c.id FROM conversations c WHERE c.institution_id = :iid
                AND c.mode = 'human' AND c.status <> 'closed'
                AND (SELECT m.direction FROM messages m WHERE m.conversation_id = c.id
                     AND m.type <> 'note' ORDER BY m.seq DESC LIMIT 1) = 'in'
                ORDER BY c.updated_at LIMIT 20"""
                ),
                iid,
            )
        )
        .scalars()
        .all()
    )
    facts = (
        await session.execute(
            text(
                """SELECT (SELECT count(*) FROM fee_items WHERE status = 'pending')
                + (SELECT count(*) FROM programs WHERE status = 'pending')
                + (SELECT count(*) FROM key_dates WHERE status = 'pending')
                + (SELECT count(*) FROM scholarships WHERE status = 'pending')
                + (SELECT count(*) FROM transport_routes WHERE status = 'pending')"""
            )
        )
    ).scalar_one()
    failed = (
        await session.execute(
            text(
                "SELECT count(*) FROM documents WHERE institution_id = :iid AND status = 'failed'"
            ),
            iid,
        )
    ).scalar_one()
    return [
        AttentionItem(
            kind="human_waiting", count=len(waiting), conversation_ids=[str(i) for i in waiting]
        ),
        AttentionItem(
            kind="flagged", count=len(flagged), conversation_ids=[str(i) for i in flagged]
        ),
        AttentionItem(kind="facts_pending", count=int(facts or 0)),
        AttentionItem(kind="documents_failed", count=int(failed or 0)),
    ]


@router.get("/response-times")
async def response_times(
    ctx: StaffCtx, session: SessionDep, range: Range = "30d"
) -> dict[str, Any]:
    tz, d0, d1 = await _window(session, ctx, DAYS[range])
    k = await _kpis(session, {"iid": ctx.institution_id, "tz": tz, "d0": d0, "d1": d1})
    return {
        "range": range,
        "median_first_response_s": k.median_first_response_s,
        "median_staff_response_s": k.median_staff_response_s,
    }
