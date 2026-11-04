"""`/api/v1/slots`, `/api/v1/bookings` — visit / test / counselling calendar (step 5.6).

Admin+ creates/edits/deletes slots (single or bulk weekly pattern in the institution's local
time); staff+ view and manage bookings (confirm, attended, no-show, cancel, reschedule).
Capacity is enforced by the same atomic UPDATE the agent's booking tool uses. Booking changes
post a staff message into the contact's latest conversation (widget delivers it via its poll;
WhatsApp template in 6.x) — the 5.6.3 confirmation hook."""

import datetime as dt
import uuid
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update

from app.api.deps import AdminCtx, SessionDep, StaffCtx, audit_mutations
from app.core.tenancy import TenantContext
from app.models.conversations import Booking, Contact, Conversation, Lead, Slot
from app.models.core import Institution
from app.services.audit import audit_ctx, snapshot
from app.services.bookings import SlotUnavailableError, cancel_booking
from app.services.conversations import add_message

router = APIRouter(tags=["slots"], dependencies=[audit_mutations])
SlotKind = Literal["visit", "test", "counselling"]
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_BULK = 500
SLOT_FIELDS = ("kind", "starts_at", "ends_at", "capacity", "location")


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    starts_at: dt.datetime
    ends_at: dt.datetime
    capacity: int
    booked_count: int
    location: str | None


class SlotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: SlotKind
    starts_at: dt.datetime
    ends_at: dt.datetime
    capacity: int = Field(ge=1, le=500)
    location: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _order(self) -> "SlotIn":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.starts_at.tzinfo is None:
            raise ValueError("timestamps need a timezone")
        return self


class SlotPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    capacity: int | None = Field(default=None, ge=1, le=500)
    location: str | None = Field(default=None, max_length=200)


class BulkIn(BaseModel):
    """Weekly pattern in the institution's timezone, e.g. Mon–Sat 10:00/11:00 for 4 weeks."""

    model_config = ConfigDict(extra="forbid")
    kind: SlotKind
    date_from: dt.date
    date_to: dt.date
    weekdays: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = Field(min_length=1)
    times: list[str] = Field(min_length=1, max_length=24)
    duration_minutes: int = Field(ge=10, le=480)
    capacity: int = Field(ge=1, le=500)
    location: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> "BulkIn":
        if self.date_to < self.date_from or (self.date_to - self.date_from).days > 92:
            raise ValueError("date range must be 0–92 days")
        for t in self.times:
            dt.time.fromisoformat(t)  # raises ValueError → 422
        return self


class BookingOut(BaseModel):
    id: uuid.UUID
    code: str
    status: str
    student_name: str | None
    contact_id: uuid.UUID | None
    contact_name: str | None
    contact_phone: str | None
    lead_id: uuid.UUID | None
    slot: SlotOut
    created_at: dt.datetime


class BookingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["confirmed", "cancelled", "attended", "no_show"] | None = None
    slot_id: uuid.UUID | None = None  # reschedule


@router.get("/slots")
async def list_slots(
    _: StaffCtx,
    session: SessionDep,
    date_from: Annotated[dt.datetime | None, Query(alias="from")] = None,
    date_to: Annotated[dt.datetime | None, Query(alias="to")] = None,
    kind: SlotKind | None = None,
) -> list[SlotOut]:
    stmt = select(Slot).order_by(Slot.starts_at).limit(1000)
    if date_from:
        stmt = stmt.where(Slot.ends_at >= date_from)
    if date_to:
        stmt = stmt.where(Slot.starts_at < date_to)
    if kind:
        stmt = stmt.where(Slot.kind == kind)
    return [SlotOut.model_validate(s) for s in await session.scalars(stmt)]


@router.post("/slots", status_code=status.HTTP_201_CREATED)
async def create_slot(
    body: SlotIn, ctx: AdminCtx, request: Request, session: SessionDep
) -> SlotOut:
    slot = Slot(**body.model_dump())
    session.add(slot)
    await session.flush()
    await session.refresh(slot)
    await audit_ctx(
        session,
        ctx,
        request,
        action="slot.create",
        entity="slot",
        entity_id=slot.id,
        after=snapshot(slot, SLOT_FIELDS),
    )
    return SlotOut.model_validate(slot)


@router.post("/slots/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_slots(
    body: BulkIn, ctx: AdminCtx, request: Request, session: SessionDep
) -> dict[str, int]:
    inst = await session.get(Institution, ctx.institution_id)
    zone = ZoneInfo(inst.timezone if inst else "Asia/Karachi")
    existing = {
        s
        for s in await session.scalars(
            select(Slot.starts_at).where(
                Slot.kind == body.kind,
                Slot.starts_at >= dt.datetime.combine(body.date_from, dt.time(), zone),
                Slot.starts_at
                < dt.datetime.combine(body.date_to + dt.timedelta(days=1), dt.time(), zone),
            )
        )
    }
    created = skipped = 0
    day = body.date_from
    while day <= body.date_to:
        if WEEKDAYS[day.weekday()] in body.weekdays:
            for t in sorted(set(body.times)):
                begin = dt.datetime.combine(day, dt.time.fromisoformat(t), zone)
                if begin in existing:  # idempotent re-run: same kind + start → skip
                    skipped += 1
                    continue
                if created >= MAX_BULK:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_CONTENT, f"max {MAX_BULK} slots per request"
                    )
                session.add(
                    Slot(
                        kind=body.kind,
                        starts_at=begin,
                        ends_at=begin + dt.timedelta(minutes=body.duration_minutes),
                        capacity=body.capacity,
                        location=body.location,
                    )
                )
                created += 1
        day += dt.timedelta(days=1)
    await session.flush()
    await audit_ctx(
        session,
        ctx,
        request,
        action="slot.bulk_create",
        entity="slot",
        after={**body.model_dump(mode="json"), "created": created, "skipped": skipped},
    )
    return {"created": created, "skipped": skipped}


async def _slot(session: SessionDep, slot_id: uuid.UUID) -> Slot:
    slot = await session.scalar(select(Slot).where(Slot.id == slot_id))
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
    return slot


@router.patch("/slots/{slot_id}")
async def patch_slot(
    slot_id: uuid.UUID, body: SlotPatch, ctx: AdminCtx, request: Request, session: SessionDep
) -> SlotOut:
    slot = await _slot(session, slot_id)
    before = snapshot(slot, SLOT_FIELDS)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None or key == "location":
            setattr(slot, key, value)
    if slot.ends_at <= slot.starts_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "ends_at must be after starts_at"
        )
    if slot.capacity < slot.booked_count:
        raise HTTPException(status.HTTP_409_CONFLICT, "Capacity below current bookings")
    await session.flush()
    await audit_ctx(
        session,
        ctx,
        request,
        action="slot.update",
        entity="slot",
        entity_id=slot.id,
        before=before,
        after=snapshot(slot, SLOT_FIELDS),
    )
    return SlotOut.model_validate(slot)


@router.delete("/slots/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot(
    slot_id: uuid.UUID, ctx: AdminCtx, request: Request, session: SessionDep
) -> None:
    slot = await _slot(session, slot_id)
    active = await session.scalar(
        select(Booking.id).where(Booking.slot_id == slot.id, Booking.status != "cancelled")
    )
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slot has bookings — cancel them first")
    before = snapshot(slot, SLOT_FIELDS)
    await session.delete(slot)  # cancelled bookings cascade with it
    await session.flush()
    await audit_ctx(
        session,
        ctx,
        request,
        action="slot.delete",
        entity="slot",
        entity_id=slot_id,
        before=before,
    )


def _booking_out(b: Booking, s: Slot, c: Contact | None) -> BookingOut:
    return BookingOut(
        id=b.id,
        code=b.code,
        status=b.status,
        student_name=b.student_name,
        contact_id=b.contact_id,
        contact_name=c.name if c else None,
        contact_phone=c.phone if c else None,
        lead_id=b.lead_id,
        slot=SlotOut.model_validate(s),
        created_at=b.created_at,
    )


@router.get("/bookings")
async def list_bookings(
    _: StaffCtx,
    session: SessionDep,
    date_from: Annotated[dt.datetime | None, Query(alias="from")] = None,
    date_to: Annotated[dt.datetime | None, Query(alias="to")] = None,
    status_: Annotated[str | None, Query(alias="status", max_length=16)] = None,
    slot_id: uuid.UUID | None = None,
) -> list[BookingOut]:
    stmt = (
        select(Booking, Slot, Contact)
        .join(Slot, Slot.id == Booking.slot_id)
        .outerjoin(Contact, Contact.id == Booking.contact_id)
        .order_by(Slot.starts_at)
        .limit(1000)
    )
    if date_from:
        stmt = stmt.where(Slot.starts_at >= date_from)
    if date_to:
        stmt = stmt.where(Slot.starts_at < date_to)
    if status_:
        stmt = stmt.where(Booking.status == status_)
    if slot_id:
        stmt = stmt.where(Booking.slot_id == slot_id)
    return [_booking_out(b, s, c) for b, s, c in (await session.execute(stmt)).all()]


async def notify_contact(
    session: SessionDep, ctx: TenantContext, contact_id: uuid.UUID | None, text: str
) -> None:
    """5.6.3: post the change into the contact's latest conversation (staff-authored, so the
    widget poll delivers it; WhatsApp sends it as a template in 6.x)."""
    if contact_id is None:
        return
    conv = await session.scalar(
        select(Conversation)
        .where(Conversation.contact_id == contact_id)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    if conv is None:
        return
    await add_message(
        session,
        conv,
        direction="out",
        sender="staff",
        text=text,
        author_user_id=ctx.user_id,
        status="sent" if conv.channel == "widget" else "queued",
    )


def _when(s: Slot, tz: str) -> str:
    return s.starts_at.astimezone(ZoneInfo(tz)).strftime("%a %d %b, %I:%M %p")


@router.patch("/bookings/{booking_id}")
async def patch_booking(
    booking_id: uuid.UUID, body: BookingPatch, ctx: StaffCtx, request: Request, session: SessionDep
) -> BookingOut:
    booking = await session.scalar(select(Booking).where(Booking.id == booking_id))
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")
    inst = await session.get(Institution, ctx.institution_id)
    tz = inst.timezone if inst else "Asia/Karachi"
    before = {"status": booking.status, "slot_id": str(booking.slot_id)}
    if body.slot_id and body.slot_id != booking.slot_id:
        if booking.status == "cancelled":
            raise HTTPException(status.HTTP_409_CONFLICT, "Booking is cancelled")
        target = await _slot(session, body.slot_id)
        taken = await session.scalar(
            update(Slot)
            .where(Slot.id == target.id, Slot.booked_count < Slot.capacity)
            .values(booked_count=Slot.booked_count + 1)
            .returning(Slot.id)
        )
        if taken is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Target slot is full")
        await session.execute(
            update(Slot)
            .where(Slot.id == booking.slot_id, Slot.booked_count > 0)
            .values(booked_count=Slot.booked_count - 1)
        )
        booking.slot_id = target.id
        await session.refresh(target)
        await notify_contact(
            session,
            ctx,
            booking.contact_id,
            f"Your {target.kind} (booking {booking.code}) has been moved to {_when(target, tz)}.",
        )
    if body.status == "cancelled":
        try:
            await cancel_booking(session, booking.id)
        except (LookupError, SlotUnavailableError):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found") from None
        await notify_contact(
            session,
            ctx,
            booking.contact_id,
            f"Your booking {booking.code} has been cancelled. Reply here to pick another time.",
        )
    elif body.status:
        if booking.status == "cancelled":
            raise HTTPException(status.HTTP_409_CONFLICT, "Booking is cancelled")
        booking.status = body.status
        if body.status == "confirmed":
            slot = await _slot(session, booking.slot_id)
            await notify_contact(
                session,
                ctx,
                booking.contact_id,
                f"Your {slot.kind} on {_when(slot, tz)} is confirmed (code {booking.code}).",
            )
    if booking.lead_id and booking.status == "attended":
        lead = await session.get(Lead, booking.lead_id)
        if lead is not None and lead.status in ("new", "contacted"):
            lead.status = "visit_booked"
    await session.flush()
    await audit_ctx(
        session,
        ctx,
        request,
        action="booking.update",
        entity="booking",
        entity_id=booking.id,
        before=before,
        after={"status": booking.status, "slot_id": str(booking.slot_id)},
    )
    slot = await _slot(session, booking.slot_id)
    contact = await session.get(Contact, booking.contact_id) if booking.contact_id else None
    return _booking_out(booking, slot, contact)
