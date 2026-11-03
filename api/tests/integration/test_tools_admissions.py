"""Step 3.4 — admissions tools against the RLS-enforced test DB: approved-only facts with
citations, tenant scoping, lead dedupe, slots/booking capacity, follow-ups, permission gates."""

import datetime as dt
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.agent.registry import ToolContext, ToolOutcome, ToolRuntime
from app.agent.tools import build_registry
from app.core.config import Settings
from app.db.session import make_sessionmaker
from app.kb.embeddings import make_provider
from app.models.conversations import Booking, Contact, Conversation, Followup, Lead, Slot
from app.seeds.schema import SEEDS_DIR
from app.services.conversations import get_or_create_contact, open_conversation
from tests.support import Factory, as_tenant, auth_headers, ingest, run, upload

pytestmark = pytest.mark.integration
NOW = dt.datetime(2026, 11, 3, 5, 0, tzinfo=dt.UTC)  # Tue 10:00 PKT
PKT = dt.timezone(dt.timedelta(hours=5))


@dataclass
class Env:
    tenant_id: uuid.UUID
    ctx: ToolContext
    runtime: ToolRuntime
    engine: AsyncEngine
    settings: Settings

    def call(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        return run(build_registry().execute(name, args, self.ctx, self.runtime, tool_use_id="t"))

    def q(self, fn: Any) -> Any:
        return run(as_tenant(self.settings, self.tenant_id, fn))


def make_env(settings: Settings, tenant_id: uuid.UUID, visitor: str = "v1") -> Env:
    async def mk(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
        contact = await get_or_create_contact(session, widget_visitor_id=visitor)
        conv = await open_conversation(session, contact, channel="widget")
        return contact.id, conv.id

    ids: tuple[uuid.UUID, uuid.UUID] = run(as_tenant(settings, tenant_id, mk))
    contact_id, conv_id = ids
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    ctx = ToolContext(
        institution_id=tenant_id,
        contact_id=contact_id,
        conversation_id=conv_id,
        channel="widget",
        verified=False,
        institution_type="school",
        timezone="Asia/Karachi",
        now=NOW,
    )
    runtime = ToolRuntime(sessionmaker=make_sessionmaker(engine), embedder=make_provider(settings))
    return Env(tenant_id, ctx, runtime, engine, settings)


def ingest_fees(client: TestClient, factory: Factory, settings: Settings) -> uuid.UUID:
    t = factory.tenant()
    admin = auth_headers(client, t.emails["admin"], t.id)
    doc = upload(
        client,
        admin,
        SEEDS_DIR / "abc_grammar_school" / "docs" / "fee_structure.xlsx",
        title="ABC fee structure",
    ).json()
    run(ingest(settings, t.id, uuid.UUID(doc["id"])))
    for kind in ("fee_items", "transport_routes"):
        rows = client.get(f"/api/v1/kb/facts/{kind}", headers=admin).json()
        ids = [r["id"] for r in rows if r["fields"].get("class_name") != "Class 10"]
        body = {"ids": ids, "status": "approved"}
        client.patch(f"/api/v1/kb/facts/{kind}", json=body, headers=admin)
    return t.id


@pytest.fixture
def two(client: TestClient, factory: Factory, it_settings: Settings) -> Iterator[tuple[Env, Env]]:
    a = make_env(it_settings, ingest_fees(client, factory, it_settings))
    b = make_env(it_settings, factory.tenant().id)
    yield a, b
    run(a.engine.dispose())
    run(b.engine.dispose())


def test_fee_table_serves_only_approved_rows_with_sources(two: tuple[Env, Env]) -> None:
    a, b = two
    out = a.call("get_fee_table", {"program_or_class": "Class 3", "academic_year": None})
    assert not out.is_error and out.data
    rows = [r["fields"] for r in out.data["rows"]]
    assert {(r.get("class_name"), r["head"], r["amount_pkr"]) for r in rows} >= {
        ("Class 3", "Tuition fee", 12500),
        ("All classes", "Admission fee", 25000),
    }
    assert all(r.get("class_name") in ("Class 3", "All classes") for r in rows)
    assert not any(r.get("class_name") == "Class 13" for r in rows)
    ids = {s.id for s in a.ctx.sources}
    assert {r["source_id"] for r in out.data["rows"]} <= ids
    cited = [s for s in a.ctx.sources if s.kind == "fact"]
    assert cited[0].citation and cited[0].citation["title"] == "ABC fee structure"
    # deterministic source ids (cassette-stable)
    again = a.call("get_fee_table", {"program_or_class": "Class 3", "academic_year": None})
    assert again.data and [r["source_id"] for r in again.data["rows"]] == [
        r["source_id"] for r in out.data["rows"]
    ]
    # pending rows (Class 10 left unapproved) are never served
    c10 = a.call("get_fee_table", {"program_or_class": "Class 10", "academic_year": None})
    assert (
        c10.data
        and c10.data["note"]
        and all(r["fields"].get("class_name") != "Class 10" for r in c10.data["rows"])
    )
    # tenant B has no facts and cannot see A's
    empty = b.call("get_fee_table", {"program_or_class": None, "academic_year": None})
    assert empty.data == {"kind": "fee_items", "rows": [], "note": None}
    assert "No approved data" in empty.content


def test_transport_filter_and_knowledge_search(two: tuple[Env, Env]) -> None:
    a, b = two
    dha = a.call("get_transport_routes", {"area": "DHA"})
    assert [r["fields"]["name"] for r in dha.data["rows"]] == ["DHA"]  # type: ignore[index]
    assert dha.data["rows"][0]["fields"]["monthly_pkr"] == 8500  # type: ignore[index]
    nowhere = a.call("get_transport_routes", {"area": "Bahria Town"})
    assert nowhere.data and nowhere.data["note"] and len(nowhere.data["rows"]) == 4
    found = a.call("search_knowledge", {"queries": ["class 5 monthly fee"], "top_k": 3})
    assert not found.is_error and found.content.startswith('<source id="S-')
    assert any(s.kind == "chunk" and s.citation for s in a.ctx.sources)
    assert b.call("search_knowledge", {"queries": ["class 5 monthly fee"], "top_k": 3}).data == {
        "results": []
    }


def test_save_lead_dedupes_by_phone_and_links_conversation(two: tuple[Env, Env]) -> None:
    a, _ = two
    bad = a.call(
        "save_lead",
        {
            "student_name": None,
            "guardian_name": None,
            "phone": "12345",
            "interest": "Class 3",
            "notes": None,
        },
    )
    assert bad.is_error and "re-check" in bad.content
    first = a.call(
        "save_lead",
        {
            "student_name": "Hamza",
            "guardian_name": None,
            "phone": None,
            "interest": "Class 3",
            "notes": "asked about DHA van",
        },
    )
    assert first.data and first.data["missing_fields"] == ["guardian_name", "phone"]
    second = a.call(
        "save_lead",
        {
            "student_name": None,
            "guardian_name": "Ayesha Malik",
            "phone": "0300-1234567",
            "interest": "Class 3",
            "notes": None,
        },
    )
    assert second.data and second.data["lead_id"] == first.data["lead_id"]
    assert second.data["missing_fields"] == []

    async def check(session: AsyncSession) -> tuple[int, Lead, Conversation, Contact]:
        n = await session.scalar(select(func.count()).select_from(Lead))
        lead = await session.scalar(select(Lead))
        conv = await session.get(Conversation, a.ctx.conversation_id)
        contact = await session.get(Contact, a.ctx.contact_id)
        return int(n or 0), lead, conv, contact  # type: ignore[return-value]

    n, lead, conv, contact = a.q(check)
    assert n == 1 and lead.phone == "+923001234567" and lead.source == "widget"
    assert lead.student_name == "Hamza" and "DHA" in (lead.notes or "")
    assert conv.lead_id == lead.id and contact.phone == "+923001234567"
    assert {"type": "lead_saved", "lead_id": str(lead.id), "has_phone": True} in a.ctx.events


def _slots(env: Env, *starts: dt.datetime, capacity: int = 1) -> None:
    async def mk(session: AsyncSession) -> None:
        for s in starts:
            session.add(
                Slot(
                    kind="visit",
                    starts_at=s,
                    ends_at=s + dt.timedelta(hours=1),
                    capacity=capacity,
                    location="Main campus reception",
                )
            )

    env.q(mk)


def test_slots_and_booking_with_capacity(two: tuple[Env, Env]) -> None:
    a, b = two
    past = dt.datetime(2026, 11, 2, 10, 0, tzinfo=PKT)
    wed = dt.datetime(2026, 11, 4, 10, 0, tzinfo=PKT)
    sat = dt.datetime(2026, 11, 7, 11, 0, tzinfo=PKT)
    far = dt.datetime(2026, 12, 20, 11, 0, tzinfo=PKT)
    _slots(a, past, wed, sat, far)
    _slots(b, dt.datetime(2026, 11, 5, 9, 0, tzinfo=PKT))
    out = a.call("get_visit_slots", {"kind": "visit", "from_date": None, "to_date": None})
    assert [s["slot_time"] for s in out.data["slots"]] == ["2026-11-04 10:00", "2026-11-07 11:00"]  # type: ignore[index]
    assert out.data["slots"][0]["label"] == "Wed 4 Nov 2026, 10:00 AM"  # type: ignore[index]

    args = {
        "kind": "visit",
        "slot_time": "2026-11-07 11:00",
        "name": "Ayesha",
        "phone": "0300 1234567",
        "student_name": "Hamza",
    }
    booked = a.call("book_visit", args)
    assert not booked.is_error, booked.content
    assert booked.data and len(booked.data["booking_code"]) == 6
    assert booked.data["when"] == "Sat 7 Nov 2026, 11:00 AM"
    full = a.call("book_visit", args)
    assert full.is_error and "filled up" in full.content
    assert a.call("book_visit", {**args, "slot_time": "2026-11-02 10:00"}).is_error  # past
    assert a.call("book_visit", {**args, "phone": "123"}).is_error
    # B's slot time does not exist for A (RLS + ORM filter)
    foreign = a.call("book_visit", {**args, "slot_time": "2026-11-05 09:00"})
    assert foreign.is_error and "No slot" in foreign.content

    async def check(session: AsyncSession) -> tuple[list[Booking], Lead | None]:
        return list((await session.scalars(select(Booking))).all()), await session.scalar(
            select(Lead)
        )

    bookings, lead = a.q(check)
    assert len(bookings) == 1 and bookings[0].student_name == "Hamza"
    assert lead is not None and lead.status == "visit_booked" and bookings[0].lead_id == lead.id
    remaining = a.call("get_visit_slots", {"kind": "visit", "from_date": None, "to_date": None})
    assert [s["slot_time"] for s in remaining.data["slots"]] == ["2026-11-04 10:00"]  # type: ignore[index]


def test_followup_language_and_handoff(two: tuple[Env, Env]) -> None:
    a, _ = two
    assert a.call("schedule_followup", {"when": "2026-11-03", "reason": "x"}).is_error
    assert a.call("schedule_followup", {"when": "2027-06-01", "reason": "x"}).is_error
    ok = a.call("schedule_followup", {"when": "2026-11-10", "reason": "decide after salary"})
    assert ok.data and ok.data["scheduled_for"] == "Tue 10 Nov 2026, 10:00 AM"
    lang = a.call("set_contact_language", {"language": "roman_ur"})
    assert not lang.is_error
    hand = a.call(
        "handoff_to_human",
        {"reason": "complaint", "summary": "Parent unhappy with response time", "urgency": "high"},
    )
    assert not hand.is_error and a.ctx.events[-1]["type"] == "handoff"

    async def check(session: AsyncSession) -> tuple[Followup | None, Contact | None]:
        return await session.scalar(select(Followup)), await session.get(Contact, a.ctx.contact_id)

    followup, contact = a.q(check)
    assert followup is not None and followup.kind == "lead_followup"
    assert followup.due_at == dt.datetime(2026, 11, 10, 10, 0, tzinfo=PKT)
    assert contact is not None and contact.preferred_language == "roman_ur"
