"""Usage: record_usage increments, nightly rollup (local-day windows, idempotent), /usage (1.6)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.conversations import Booking, Contact, Conversation, Lead, LlmRun, Message, Slot
from app.models.core import UsageDaily
from app.services.usage import record_usage, rollup_usage
from tests.support import Factory, Tenant, as_admin, as_tenant, auth_headers, run

pytestmark = pytest.mark.integration

DAY = date(2027, 2, 10)
# Asia/Karachi is UTC+5: 2027-02-10 local = [2027-02-09 19:00Z, 2027-02-10 19:00Z)
IN_DAY = datetime(2027, 2, 10, 6, 0, tzinfo=UTC)
LATE_UTC_NEXT_LOCAL_DAY = datetime(2027, 2, 10, 20, 0, tzinfo=UTC)
EARLY_UTC_SAME_LOCAL_DAY = datetime(2027, 2, 9, 19, 30, tzinfo=UTC)


def populate(settings: Settings, t: Tenant) -> None:
    async def go(session: AsyncSession) -> None:
        contact = Contact(wa_id="923001112223")
        session.add(contact)
        await session.flush()
        c1 = Conversation(
            contact_id=contact.id, channel="whatsapp", thread_id="x", created_at=IN_DAY
        )
        c2 = Conversation(
            contact_id=contact.id,
            channel="widget",
            thread_id="x",
            created_at=LATE_UTC_NEXT_LOCAL_DAY,
        )
        session.add_all([c1, c2])
        await session.flush()
        for direction, sender, typ, at in [
            ("in", "contact", "text", EARLY_UTC_SAME_LOCAL_DAY),
            ("in", "contact", "audio", IN_DAY),
            ("out", "ai", "text", IN_DAY),
            ("out", "staff", "template", IN_DAY),
            ("out", "system", "note", IN_DAY),
            ("in", "contact", "text", LATE_UTC_NEXT_LOCAL_DAY),
        ]:
            session.add(
                Message(
                    conversation_id=c1.id,
                    direction=direction,
                    sender=sender,
                    type=typ,
                    created_at=at,
                )
            )
        session.add_all(
            [
                LlmRun(
                    conversation_id=c1.id,
                    node="agent_complex",
                    model="claude-opus-5-5",
                    input_tokens=1800,
                    cache_read_tokens=8000,
                    output_tokens=900,
                    cost_usd=Decimal("0.038"),
                    created_at=IN_DAY,
                ),
                LlmRun(
                    node="router",
                    model="claude-haiku-5-5",
                    input_tokens=500,
                    output_tokens=20,
                    cost_usd=Decimal("0.00006"),
                    created_at=IN_DAY,
                ),
                Lead(source="whatsapp", created_at=IN_DAY),
            ]
        )
        slot = Slot(
            kind="visit",
            starts_at=IN_DAY + timedelta(days=3),
            ends_at=IN_DAY + timedelta(days=3, hours=1),
            capacity=3,
            booked_count=1,
        )
        session.add(slot)
        await session.flush()
        session.add(Booking(slot_id=slot.id, code="ABC234", created_at=IN_DAY))

    run(as_tenant(settings, t.id, go))


def usage_row(settings: Settings, t: Tenant, day: date) -> UsageDaily | None:
    async def q(session: AsyncSession) -> UsageDaily | None:
        return await session.scalar(
            select(UsageDaily).where(UsageDaily.institution_id == t.id, UsageDaily.date == day)
        )

    return run(as_admin(settings, q))


def test_rollup_uses_local_day_and_is_idempotent(it_settings: Settings, factory: Factory) -> None:
    t, other = factory.tenant(("owner",)), factory.tenant(("owner",))
    populate(it_settings, t)

    async def roll(session: AsyncSession) -> int:
        return await rollup_usage(session, DAY)

    assert run(as_admin(it_settings, roll)) >= 2
    run(as_admin(it_settings, roll))  # second run overwrites, no double counting
    row = usage_row(it_settings, t, DAY)
    assert row is not None
    assert (row.conversations, row.messages_in, row.messages_out, row.template_sends) == (
        1,
        2,
        2,
        1,
    )
    assert (row.tokens_in, row.tokens_out) == (1800 + 8000 + 500, 920)
    assert row.llm_cost_usd == Decimal("0.038060")
    assert (row.leads, row.bookings) == (1, 1)
    zero = usage_row(it_settings, other, DAY)
    assert zero is not None
    assert zero.messages_in == 0


def test_record_usage_increments_and_rollup_keeps_fee_recovered(
    it_settings: Settings, factory: Factory
) -> None:
    t = factory.tenant(("owner",))

    async def go(session: AsyncSession) -> None:
        await record_usage(session, t.id, DAY, template_sends=2, fee_recovered_pkr=12500)
        await record_usage(session, t.id, DAY, template_sends=3)
        with pytest.raises(ValueError, match="unknown usage counters"):
            await record_usage(session, t.id, DAY, bogus=1)

    run(as_admin(it_settings, go))
    row = usage_row(it_settings, t, DAY)
    assert row is not None
    assert (row.template_sends, row.fee_recovered_pkr) == (5, 12500)

    async def roll(session: AsyncSession) -> int:
        return await rollup_usage(session, DAY)

    run(as_admin(it_settings, roll))
    row = usage_row(it_settings, t, DAY)
    assert row is not None
    assert (row.template_sends, row.fee_recovered_pkr) == (0, 12500)


def test_usage_endpoint(client: TestClient, it_settings: Settings, factory: Factory) -> None:
    t = factory.tenant()

    async def go(session: AsyncSession) -> None:
        await record_usage(session, t.id, DAY, messages_in=4, llm_cost_usd=Decimal("0.5"))
        await record_usage(session, t.id, DAY + timedelta(days=1), messages_in=6)

    run(as_admin(it_settings, go))
    admin = auth_headers(client, t.emails["admin"], t.id)
    r = client.get("/api/v1/usage?from=2027-02-10&to=2027-02-11", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [d["date"] for d in body["days"]] == ["2027-02-10", "2027-02-11"]
    assert body["totals"]["messages_in"] == 10
    assert Decimal(body["totals"]["llm_cost_usd"]) == Decimal("0.5")
    bad = client.get("/api/v1/usage?from=2027-02-11&to=2027-02-10", headers=admin)
    assert bad.status_code == 400
    staff = auth_headers(client, t.emails["staff"], t.id)
    assert client.get("/api/v1/usage", headers=staff).status_code == 403
