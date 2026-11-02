"""Conversation domain: CRUD via tenant-scoped services, uniques, indexes, capacity (step 1.4)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.tenancy import tenant_session
from app.db.session import make_sessionmaker
from app.models.conversations import Contact, Lead, LlmRun, Slot
from app.services import bookings, conversations
from tests.support import Factory

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine(it_settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(it_settings.database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
def sm(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


async def test_contact_conversation_messages_roundtrip(
    sm: async_sessionmaker[AsyncSession], factory: Factory
) -> None:
    t = await factory.atenant(("owner",))
    async with tenant_session(sm, t.id) as s:
        contact = await conversations.get_or_create_contact(s, wa_id="923001234567", name="Ali")
        again = await conversations.get_or_create_contact(s, wa_id="923001234567")
        assert again.id == contact.id
        assert contact.institution_id == t.id
        conv = await conversations.open_conversation(s, contact, channel="whatsapp")
        assert conv.thread_id == f"{t.id}:{contact.id}"
        assert conv.mode == "ai"
        await conversations.add_message(
            s, conv, direction="in", sender="contact", text="Fee kitni hai?"
        )
        await conversations.add_message(
            s,
            conv,
            direction="out",
            sender="ai",
            text="Class 5 ki monthly fee PKR 12,500 hai.",
            citations=[{"document_id": str(uuid.uuid4()), "page": 3}],
        )
        assert (await conversations.open_conversation(s, contact, channel="whatsapp")).id == conv.id
        msgs = await conversations.list_messages(s, conv.id)
        assert [m.sender for m in msgs] == ["contact", "ai"]
        assert msgs[1].status == "queued"
        assert conv.last_inbound_at is not None
        s.add(
            LlmRun(
                conversation_id=conv.id,
                node="agent_simple",
                model="claude-haiku-5-5",
                skills=["admissions_faq"],
                input_tokens=1800,
                output_tokens=120,
            )
        )
        s.add(
            Lead(contact_id=contact.id, source="whatsapp", student_name="Hamza", interest="Class 5")
        )
        await s.flush()


async def test_wa_id_unique_per_institution_not_globally(
    sm: async_sessionmaker[AsyncSession], factory: Factory
) -> None:
    a, b = await factory.atenant(("owner",)), await factory.atenant(("owner",))
    for t in (a, b):  # same parent can talk to two schools
        async with tenant_session(sm, t.id) as s:
            await conversations.get_or_create_contact(s, wa_id="923339999999")
    async with tenant_session(sm, a.id) as s:
        s.add(Contact(wa_id="923339999999"))
        with pytest.raises(IntegrityError, match="uq_contacts_institution_id_wa_id"):
            await s.flush()
        await s.rollback()


async def test_slot_capacity_enforced_and_cancel_frees_seat(
    sm: async_sessionmaker[AsyncSession], factory: Factory
) -> None:
    t = await factory.atenant(("owner",))
    start = datetime(2027, 2, 15, 5, 0, tzinfo=UTC)
    async with tenant_session(sm, t.id) as s:
        slot = Slot(kind="visit", starts_at=start, ends_at=start + timedelta(hours=1), capacity=2)
        s.add(slot)
        await s.flush()
        b1 = await bookings.book_slot(s, slot.id, student_name="Ayan")
        await bookings.book_slot(s, slot.id, student_name="Zara")
        with pytest.raises(bookings.SlotUnavailableError):
            await bookings.book_slot(s, slot.id, student_name="Late")
        assert len(b1.code) == 6
        await bookings.cancel_booking(s, b1.id)
        await bookings.cancel_booking(s, b1.id)  # idempotent
        refreshed = await s.scalar(
            select(Slot.booked_count)
            .where(Slot.id == slot.id)
            .execution_options(populate_existing=True)
        )
        assert refreshed == 1


async def test_other_tenant_cannot_book_my_slot(
    sm: async_sessionmaker[AsyncSession], factory: Factory
) -> None:
    a, b = await factory.atenant(("owner",)), await factory.atenant(("owner",))
    start = datetime(2027, 3, 1, 5, 0, tzinfo=UTC)
    async with tenant_session(sm, a.id) as s:
        slot = Slot(kind="test", starts_at=start, ends_at=start + timedelta(hours=2), capacity=5)
        s.add(slot)
        await s.flush()
    async with tenant_session(sm, b.id) as s:
        with pytest.raises(bookings.SlotUnavailableError):
            await bookings.book_slot(s, slot.id)


async def test_expected_indexes_and_checkpoint_tables(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        idx = set(
            (await conn.execute(text("select indexname from pg_indexes where schemaname='public'")))
            .scalars()
            .all()
        )
        tables = set(
            (await conn.execute(text("select tablename from pg_tables where schemaname='public'")))
            .scalars()
            .all()
        )
    for table in (
        "contacts",
        "conversations",
        "messages",
        "llm_runs",
        "leads",
        "bookings",
        "followups",
    ):
        assert f"ix_{table}_institution_id_created_at" in idx, table
    assert {
        "uq_contacts_institution_id_wa_id",
        "uq_messages_wa_message_id",
        "uq_messages_conversation_id_client_msg_id",
        "ix_slots_institution_id_starts_at",
        "ix_followups_status_due_at",
    } <= idx
    assert {"checkpoints", "checkpoint_writes", "checkpoint_blobs"} <= tables
