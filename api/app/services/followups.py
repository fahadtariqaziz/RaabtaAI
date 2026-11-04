"""Scheduler-driven outbound flow (step 6.7, PLAN §6.2): no LLM on the hot path.

`dispatch_due` (arq cron, every minute): collect booking reminders (day before, from 10:00 local)
→ due `followups` rows → policy gate (opt-out, staff mode, plan limit, quiet hours/Jumma, weekly
cap) → render template → send (free-form inside the 24h window, template outside) → mark."""

import datetime as dt
import logging
import uuid
from collections import defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp.policy import gate
from app.channels.whatsapp.templates import TemplateError
from app.core.tenancy import admin_session, tenant_session
from app.models.conversations import Booking, Contact, Conversation, Followup, Lead, Message, Slot
from app.models.core import Institution, Plan, UsageDaily
from app.services.whatsapp import WhatsAppDeps, send_template

log = logging.getLogger(__name__)

REMINDER_HOUR = 10
BATCH = 200
PROACTIVE_KINDS_TEMPLATE = {
    "lead_followup": "admission_followup_1",
    "admission_followup_1": "admission_followup_1",
    "admission_followup_2": "admission_followup_2",
    "visit_reminder": "visit_reminder",
}


def fmt_local(when: dt.datetime, tz: str) -> str:
    return when.astimezone(ZoneInfo(tz)).strftime("%a %d %b, %I:%M %p")


async def schedule_booking_reminders(
    session: AsyncSession, inst: Institution, now: dt.datetime
) -> int:
    """Create a `visit_reminder` follow-up for each active booking whose slot starts tomorrow
    (institution tz), once it is past 10:00 local today. Idempotent via payload.booking_id."""
    tz = ZoneInfo(inst.timezone)
    local = now.astimezone(tz)
    if local.hour < REMINDER_HOUR:
        return 0
    tomorrow = local.date() + dt.timedelta(days=1)
    start = dt.datetime.combine(tomorrow, dt.time(0), tz)
    end = start + dt.timedelta(days=1)
    rows = (
        await session.execute(
            select(Booking.id, Booking.contact_id, Booking.lead_id)
            .join(Slot, Slot.id == Booking.slot_id)
            .where(
                Booking.status.in_(("booked", "confirmed")),
                Booking.reminder_sent_at.is_(None),
                Booking.contact_id.is_not(None),
                Slot.starts_at >= start,
                Slot.starts_at < end,
            )
        )
    ).all()
    made = 0
    for booking_id, contact_id, lead_id in rows:
        exists = await session.scalar(
            select(Followup.id).where(
                Followup.kind == "visit_reminder",
                Followup.payload["booking_id"].astext == str(booking_id),
            )
        )
        if exists is None:
            session.add(
                Followup(
                    contact_id=contact_id,
                    lead_id=lead_id,
                    kind="visit_reminder",
                    template_name="visit_reminder",
                    due_at=now,
                    payload={"booking_id": str(booking_id)},
                )
            )
            made += 1
    return made


async def _proactive_sent_7d(session: AsyncSession, contact_id: uuid.UUID, now: dt.datetime) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.contact_id == contact_id,
                Message.direction == "out",
                Message.sender == "system",
                Message.template_name.is_not(None),
                Message.status != "failed",
                Message.created_at >= now - dt.timedelta(days=7),
            )
        )
        or 0
    )


async def over_plan_limit(session: AsyncSession, inst: Institution, now: dt.datetime) -> bool:
    if inst.plan_id is None:
        return False
    plan = await session.get(Plan, inst.plan_id)
    if plan is None or not plan.monthly_template_sends:
        return False
    tz = ZoneInfo(inst.timezone)
    month_start = now.astimezone(tz).date().replace(day=1)
    rolled = await session.scalar(
        select(func.coalesce(func.sum(UsageDaily.template_sends), 0)).where(
            UsageDaily.institution_id == inst.id, UsageDaily.date >= month_start
        )
    )
    today_start = dt.datetime.combine(now.astimezone(tz).date(), dt.time(0), tz)
    today = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.direction == "out",
            Message.type == "template",
            Message.created_at >= today_start,
        )
    )
    return int(rolled or 0) + int(today or 0) >= plan.monthly_template_sends


async def _values(
    session: AsyncSession, inst: Institution, fu: Followup, contact: Contact
) -> dict[str, Any]:
    name = contact.name
    if fu.lead_id is not None:
        lead = await session.get(Lead, fu.lead_id)
        name = name or (lead.guardian_name if lead else None)
    values: dict[str, Any] = {"name": name or "Sahib/Sahiba", "institution": inst.name}
    booking_id = (fu.payload or {}).get("booking_id")
    if booking_id:
        booking = await session.get(Booking, uuid.UUID(booking_id))
        slot = await session.get(Slot, booking.slot_id) if booking else None
        if booking is None or slot is None:
            raise TemplateError("booking not found")
        values |= {
            "date": fmt_local(slot.starts_at, inst.timezone),
            "place": slot.location or inst.name,
            "code": booking.code,
        }
    return values


async def process_followup(
    deps: WhatsAppDeps, session: AsyncSession, inst: Institution, fu: Followup, now: dt.datetime
) -> str:
    contact = await session.get(Contact, fu.contact_id) if fu.contact_id else None
    if contact is None and fu.lead_id is not None:
        lead = await session.get(Lead, fu.lead_id)
        contact = await session.get(Contact, lead.contact_id) if lead and lead.contact_id else None
    if contact is None or not contact.wa_id:
        fu.status, fu.error = "cancelled", "no WhatsApp number for this contact"
        return "cancelled"
    if fu.kind == "visit_reminder":
        booking_id = (fu.payload or {}).get("booking_id")
        booking = await session.get(Booking, uuid.UUID(booking_id)) if booking_id else None
        if booking is None or booking.status not in ("booked", "confirmed"):
            fu.status, fu.error = "cancelled", "booking no longer active"
            return "cancelled"
    conv = await session.scalar(
        select(Conversation)
        .where(Conversation.contact_id == contact.id, Conversation.channel == "whatsapp")
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    decision = gate(
        now,
        tz_name=inst.timezone,
        quiet=inst.quiet_hours,
        opted_out=contact.opted_out_at is not None,
        human_mode=conv is not None and conv.mode == "human",
        sent_last_7d=await _proactive_sent_7d(session, contact.id, now),
        over_plan=await over_plan_limit(session, inst, now),
    )
    if decision.action == "cancel":
        fu.status, fu.error = "cancelled", decision.reason
        return "cancelled"
    if decision.action == "hold":
        fu.status, fu.error = "held", decision.reason
        log.warning("followups held for institution %s: %s", inst.id, decision.reason)
        return "held"
    if decision.action == "reschedule":
        fu.due_at, fu.error = decision.when or now + dt.timedelta(hours=1), decision.reason
        return "rescheduled"
    template = fu.template_name or PROACTIVE_KINDS_TEMPLATE.get(fu.kind, "admission_followup_1")
    try:
        values = await _values(session, inst, fu, contact)
        msg = await send_template(
            deps,
            session,
            contact=contact,
            template_name=template,
            values=values,
            conversation=conv,
            now=now,
        )
    except TemplateError as exc:
        fu.status, fu.error = "failed", str(exc)[:300]
        return "failed"
    if msg.status == "failed":
        fu.status, fu.error = "failed", msg.error
        return "failed"
    fu.status, fu.sent_at, fu.error = "sent", now, None
    if fu.kind == "visit_reminder":
        booking = await session.get(Booking, uuid.UUID(fu.payload["booking_id"]))
        if booking is not None:
            booking.reminder_sent_at = now
    return "sent"


async def dispatch_due(
    deps: WhatsAppDeps,
    now: dt.datetime | None = None,
    only: set[uuid.UUID] | None = None,
) -> dict[str, int]:
    """`only` limits the run to some institutions (ops re-runs, tests)."""
    now = now or dt.datetime.now(dt.UTC)
    counts: dict[str, int] = defaultdict(int)
    async with admin_session(deps.sessionmaker) as session:
        inst_ids = list(
            (
                await session.scalars(
                    select(Institution.id).where(
                        Institution.status != "suspended",
                        Institution.wa_phone_number_id.is_not(None),
                    )
                )
            ).all()
        )
        due_q = (
            select(Followup.institution_id, Followup.id)
            .where(Followup.status == "pending", Followup.due_at <= now)
            .order_by(Followup.due_at)
            .limit(BATCH)
        )
        if only is not None:
            inst_ids = [i for i in inst_ids if i in only]
            due_q = due_q.where(Followup.institution_id.in_(only))
        due = (await session.execute(due_q)).all()
    by_inst: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for inst_id, fu_id in due:
        by_inst[inst_id].append(fu_id)
    for inst_id in inst_ids:
        async with tenant_session(deps.sessionmaker, inst_id) as session:
            inst = await session.get(Institution, inst_id)
            if inst is None:
                continue
            counts["reminders_scheduled"] += await schedule_booking_reminders(session, inst, now)
            await session.flush()
            fresh = (
                await session.scalars(
                    select(Followup.id).where(
                        Followup.kind == "visit_reminder",
                        Followup.status == "pending",
                        Followup.due_at <= now,
                    )
                )
            ).all()
            for fid in fresh:
                if fid not in by_inst[inst_id]:
                    by_inst[inst_id].append(fid)
    for inst_id, ids in by_inst.items():
        for fu_id in ids:
            # one transaction per follow-up: a failure never rolls back already-sent ones
            async with tenant_session(deps.sessionmaker, inst_id) as session:
                inst = await session.get(Institution, inst_id)
                fu = await session.get(Followup, fu_id, with_for_update={"skip_locked": True})
                if inst is None or fu is None or fu.status != "pending":
                    continue
                counts[await process_followup(deps, session, inst, fu, now)] += 1
    return dict(counts)
