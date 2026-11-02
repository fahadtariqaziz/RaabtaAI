"""Slot booking with capacity enforced in one atomic UPDATE (no read-modify-write race).
Deterministic code only — the agent calls this via a tool (PLAN §9), never does arithmetic."""

import secrets
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversations import Booking, Slot

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I — read aloud on the phone


class SlotUnavailableError(Exception):
    pass


def booking_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


async def book_slot(
    session: AsyncSession,
    slot_id: uuid.UUID,
    *,
    contact_id: uuid.UUID | None = None,
    lead_id: uuid.UUID | None = None,
    student_name: str | None = None,
) -> Booking:
    taken = await session.scalar(
        update(Slot)
        .where(Slot.id == slot_id, Slot.booked_count < Slot.capacity)
        .values(booked_count=Slot.booked_count + 1)
        .returning(Slot.id)
    )
    if taken is None:
        raise SlotUnavailableError("slot is full or does not exist")
    booking = Booking(
        slot_id=slot_id,
        contact_id=contact_id,
        lead_id=lead_id,
        student_name=student_name,
        code=booking_code(),
    )
    session.add(booking)
    await session.flush()
    return booking


async def cancel_booking(session: AsyncSession, booking_id: uuid.UUID) -> Booking:
    booking = await session.scalar(select(Booking).where(Booking.id == booking_id))
    if booking is None:
        raise LookupError("booking not found")
    if booking.status != "cancelled":
        booking.status = "cancelled"
        await session.execute(
            update(Slot)
            .where(Slot.id == booking.slot_id, Slot.booked_count > 0)
            .values(booked_count=Slot.booked_count - 1)
        )
        await session.flush()
    return booking
