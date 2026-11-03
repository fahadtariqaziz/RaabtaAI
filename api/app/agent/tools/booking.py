"""Visit/test/counselling slots (PLAN §9.3). The model sees and passes local `slot_time` strings
("2026-11-04 10:00") — no database ids — and capacity is enforced atomically in
`services.bookings.book_slot`."""

import datetime as dt
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import ToolContext, ToolError, ToolRuntime
from app.agent.tools.leads import local_now, normalize_pk_phone, upsert_lead
from app.models.conversations import Slot
from app.services.bookings import SlotUnavailableError, book_slot

SlotKind = Literal["visit", "test", "counselling"]
SLOT_FMT = "%Y-%m-%d %H:%M"
DEFAULT_WINDOW_DAYS = 14
MAX_SLOTS = 8


def slot_label(starts_at: dt.datetime, tz: str) -> str:
    local = starts_at.astimezone(ZoneInfo(tz))
    return local.strftime("%a %d %b %Y, %I:%M %p").replace(" 0", " ")


class SlotsInput(BaseModel):
    kind: SlotKind
    from_date: dt.date | None = Field(description="First day to look at (YYYY-MM-DD); null=today")
    to_date: dt.date | None = Field(description="Last day (YYYY-MM-DD); null = two weeks ahead")


class SlotOut(BaseModel):
    slot_time: str
    label: str
    location: str | None
    seats_left: int


class SlotsOutput(BaseModel):
    kind: str
    slots: list[SlotOut]
    note: str | None = None


async def get_visit_slots(
    args: SlotsInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> SlotsOutput:
    tz = ZoneInfo(ctx.timezone)
    today = local_now(ctx).date()
    start_day = max(args.from_date or today, today)
    end_day = args.to_date or start_day + dt.timedelta(days=DEFAULT_WINDOW_DAYS)
    start = max(dt.datetime.combine(start_day, dt.time(0), tzinfo=tz), ctx.now)
    end = dt.datetime.combine(end_day + dt.timedelta(days=1), dt.time(0), tzinfo=tz)
    rows = (
        await session.scalars(
            select(Slot)
            .where(
                Slot.kind == args.kind,
                Slot.starts_at >= start,
                Slot.starts_at < end,
                Slot.booked_count < Slot.capacity,
            )
            .order_by(Slot.starts_at)
            .limit(MAX_SLOTS)
        )
    ).all()
    slots = [
        SlotOut(
            slot_time=s.starts_at.astimezone(tz).strftime(SLOT_FMT),
            label=slot_label(s.starts_at, ctx.timezone),
            location=s.location,
            seats_left=s.capacity - s.booked_count,
        )
        for s in rows
    ]
    note = None if slots else f"No open {args.kind} slots in that period. Offer a follow-up."
    return SlotsOutput(kind=args.kind, slots=slots, note=note)


class BookInput(BaseModel):
    kind: SlotKind
    slot_time: str = Field(description="Exactly as returned by get_visit_slots (YYYY-MM-DD HH:MM)")
    name: str = Field(min_length=1, max_length=120, description="Parent/guardian (or student) name")
    phone: str = Field(min_length=7, max_length=32, description="Phone as the contact typed it")
    student_name: str | None = Field(max_length=120, description="Student's name if given")


class BookOutput(BaseModel):
    booking_code: str
    when: str
    location: str | None
    kind: str


async def book_visit(
    args: BookInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> BookOutput:
    phone = normalize_pk_phone(args.phone)
    if phone is None:
        raise ToolError("A valid Pakistani phone number is required to book. Ask the contact.")
    try:
        naive = dt.datetime.strptime(args.slot_time.strip(), SLOT_FMT)
    except ValueError:
        raise ToolError(
            "slot_time must be YYYY-MM-DD HH:MM as returned by get_visit_slots."
        ) from None
    starts = naive.replace(tzinfo=ZoneInfo(ctx.timezone))
    if starts <= ctx.now:
        raise ToolError("That slot is in the past. Call get_visit_slots for upcoming options.")
    slot = await session.scalar(
        select(Slot).where(Slot.kind == args.kind, Slot.starts_at == starts).limit(1)
    )
    if slot is None:
        raise ToolError("No slot at that time. Call get_visit_slots and offer the listed times.")
    lead = await upsert_lead(
        session,
        ctx,
        phone=phone,
        guardian_name=args.name,
        student_name=args.student_name,
        status="visit_booked",
    )
    try:
        booking = await book_slot(
            session,
            slot.id,
            contact_id=ctx.contact_id,
            lead_id=lead.id,
            student_name=args.student_name,
        )
    except SlotUnavailableError:
        raise ToolError(
            "That slot just filled up. Offer another time from get_visit_slots."
        ) from None
    when = slot_label(slot.starts_at, ctx.timezone)
    ctx.events.append({"type": "booked", "code": booking.code, "when": when, "kind": args.kind})
    return BookOutput(booking_code=booking.code, when=when, location=slot.location, kind=args.kind)
