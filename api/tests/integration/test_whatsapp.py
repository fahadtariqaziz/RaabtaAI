"""Phase 6 end-to-end on the real DB (FakeLLM + FakeSTT + a recording Graph API over
httpx.MockTransport; zero spend, no network):

webhook verify/signature/idempotency → inbound text → AI reply delivered (privacy line, status
rows) → status webhooks → voice note (transcript + prefix / low confidence → "please type") →
opt-out (cancels follow-ups, confirms once) → 24h window (staff send refused, queued row fails) →
widget→WhatsApp session-code link → follow-up dispatch (quiet hours, template send, weekly cap,
human mode) → booking reminders → templates API (seed/submit/status webhook/sync) → summary."""

import asyncio
import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.agent.graph import AgentDeps, build_graph
from app.agent.runtime import AgentRuntime
from app.agent.tools import build_registry
from app.channels.stt import Transcript
from app.channels.stt.fake import FakeSTT
from app.channels.whatsapp.client import WhatsAppClient
from app.channels.whatsapp.webhook import InboundMessage
from app.core.config import Settings
from app.db.session import make_sessionmaker
from app.kb.embeddings import make_provider
from app.llm.fake import FakeLLM, text_reply, tool_call
from app.models.conversations import Booking, Contact, Conversation, Followup, Message, Slot
from app.models.core import Institution, WebhookEvent
from app.models.templates import Template
from app.services import followups as fu_service
from app.services.daily_summary import build_summary, send_daily_summaries
from app.services.whatsapp import (
    WhatsAppDeps,
    deliver_message,
    process_event,
    process_inbound,
)
from tests.channels import payloads as wp
from tests.integration.test_graph import FEE_CALL, GOOD, script
from tests.integration.test_tools_admissions import ingest_fees
from tests.support import Factory, as_admin, as_tenant, auth_headers

pytestmark = pytest.mark.integration
SECRET = "app-secret-test"
VERIFY = "verify-token-test"
PK = ZoneInfo("Asia/Karachi")


@dataclass
class Graph:
    """Recording stand-in for graph.facebook.com."""

    sent: list[dict[str, Any]] = field(default_factory=list)
    submitted: list[dict[str, Any]] = field(default_factory=list)
    remote_templates: list[dict[str, Any]] = field(default_factory=list)

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.url.host == "lookaside.test":
            return httpx.Response(200, content=b"OggS-fake-audio")
        if req.method == "GET" and path.endswith("/MEDIA123"):
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.test/m/1",
                    "mime_type": "audio/ogg",
                    "file_size": 15,
                },
            )
        if path.endswith("/messages"):
            body = json.loads(req.content)
            self.sent.append(body)
            return httpx.Response(200, json={"messages": [{"id": f"wamid.{uuid.uuid4().hex}"}]})
        if path.endswith("/message_templates") and req.method == "POST":
            self.submitted.append(json.loads(req.content))
            return httpx.Response(
                200, json={"id": f"tpl{len(self.submitted)}", "status": "PENDING"}
            )
        if path.endswith("/message_templates"):
            return httpx.Response(200, json={"data": self.remote_templates})
        return httpx.Response(404, json={"error": {"message": "unexpected", "code": 100}})

    def texts(self) -> list[str]:
        out = []
        for b in self.sent:
            if b["type"] == "text":
                out.append(b["text"]["body"])
            elif b["type"] == "interactive":
                out.append(b["interactive"]["body"]["text"])
            elif b["type"] == "template":
                out.append(f"TEMPLATE:{b['template']['name']}")
        return out


def agent_script() -> dict[str, Any]:
    def agent(req: dict[str, Any]) -> Any:
        return (
            text_reply(GOOD)
            if "tool_result" in json.dumps(req["messages"])
            else tool_call(*FEE_CALL)
        )

    return script(agent_simple=agent)


@dataclass
class Env:
    tenant: uuid.UUID
    pnid: str
    waba: str
    graph: Graph
    stt: FakeSTT
    deps: WhatsAppDeps
    settings: Settings
    llm: FakeLLM

    def run(self, coro: Any) -> Any:
        return asyncio.run(coro)

    def inbound(self, text: str | None = None, kind: str = "text", **kw: Any) -> str:
        m = InboundMessage(
            event_id=kw.pop("wamid", f"wamid.{uuid.uuid4().hex[:10]}"),
            phone_number_id=self.pnid,
            wa_id=kw.pop("wa_id", wp.WA_ID),
            name="Ayesha",
            kind=kind,
            text=text,
            **kw,
        )
        return str(self.run(process_inbound(self.deps, self.tenant, m)))

    def tenant_q(self, fn: Any) -> Any:
        return self.run(as_tenant(self.settings, self.tenant, fn))


@pytest.fixture
def wa(client: TestClient, factory: Factory, it_settings: Settings) -> Env:
    tenant = ingest_fees(client, factory, it_settings)
    pnid, waba = f"pn{uuid.uuid4().hex[:12]}", f"waba{uuid.uuid4().hex[:10]}"

    async def connect(session: AsyncSession) -> None:
        await session.execute(
            update(Institution)
            .where(Institution.id == tenant)
            .values(wa_phone_number_id=pnid, waba_id=waba)
        )

    asyncio.run(as_admin(it_settings, connect))
    graph = Graph()
    wa_client = WhatsAppClient("tok", transport=httpx.MockTransport(graph.handler), backoff=0)
    client.app.state.wa_client = wa_client  # type: ignore[attr-defined]
    app_settings = client.app.state.settings  # type: ignore[attr-defined]
    app_settings.meta_app_secret = SecretStr(SECRET)
    app_settings.meta_verify_token = SecretStr(VERIFY)
    llm = FakeLLM(agent_script())
    res = client.app.state.resources  # type: ignore[attr-defined]
    # Own NullPool engine: the services run under asyncio.run (a new loop per call), while the
    # app's pooled engine belongs to the TestClient loop.
    engine = create_async_engine(it_settings.database_url, poolclass=NullPool)
    sessionmaker = make_sessionmaker(engine)
    adeps = AgentDeps(
        sessionmaker=sessionmaker,
        llm=llm,
        registry=build_registry(),
        embedder=make_provider(it_settings),
    )
    runtime = AgentRuntime(adeps, build_graph(adeps, InMemorySaver()))
    client.app.state.agent.set(runtime)  # type: ignore[attr-defined]
    stt = FakeSTT()

    async def agent() -> AgentRuntime:
        return runtime

    deps = WhatsAppDeps(
        sessionmaker=sessionmaker,
        client=wa_client,
        blobstore=res.blobstore,
        redis=None,
        agent=agent,
        stt=lambda: stt,
    )
    return Env(tenant, pnid, waba, graph, stt, deps, it_settings, llm)


def _swap_pnid(payload: dict[str, Any], pnid: str, waba: str) -> dict[str, Any]:
    swapped: dict[str, Any] = json.loads(
        json.dumps(payload).replace(wp.PNID, pnid).replace(wp.WABA, waba)
    )
    return swapped


# --- 6.2 webhook -----------------------------------------------------------------------------


def test_webhook_verify_signature_idempotency(client: TestClient, wa: Env) -> None:
    url = "/api/v1/webhooks/whatsapp"
    ok = client.get(
        url, params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "42"}
    )
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get(
        url, params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "42"}
    )
    assert bad.status_code == 403

    hook = f"wamid.HOOK{uuid.uuid4().hex[:8]}"
    payload = _swap_pnid(wp.text_msg("Class 3 ki fee?", wamid=hook), wa.pnid, wa.waba)
    raw, headers = wp.signed(payload, SECRET)
    assert (
        client.post(
            url, content=raw, headers={**headers, "X-Hub-Signature-256": "sha256=00"}
        ).status_code
        == 403
    )
    first = client.post(url, content=raw, headers=headers)
    assert first.status_code == 200 and first.json() == {"received": 1, "queued": 1}
    assert client.post(url, content=raw, headers=headers).json() == {"received": 1, "queued": 0}
    other = wp.text_msg("hi", wamid=f"wamid.O{uuid.uuid4().hex[:8]}")  # unknown phone_number_id
    unknown = wp.signed(other, SECRET)
    assert client.post(url, content=unknown[0], headers=unknown[1]).json()["queued"] == 0

    async def event_id(session: AsyncSession) -> uuid.UUID:
        ev = await session.scalar(select(WebhookEvent).where(WebhookEvent.event_id == hook))
        assert ev is not None and ev.institution_id == wa.tenant and ev.status == "received"
        return ev.id

    eid: uuid.UUID = asyncio.run(as_admin(wa.settings, event_id))
    assert wa.run(process_event(wa.deps, eid)).startswith("replied")  # the worker job
    assert wa.run(process_event(wa.deps, eid)) == "skipped"  # processed once
    assert any(GOOD in t for t in wa.graph.texts())


# --- 6.3 / 6.8.4 delivery, statuses, follow-ups scheduled -----------------------------------


def test_inbound_reply_delivered_with_privacy_line_and_statuses(wa: Env) -> None:
    assert wa.inbound("Class 3 ki fee kitni hai?").startswith("replied:sent")
    first = wa.graph.texts()[-1]
    assert GOOD in first and "STOP" in first  # privacy line on the first reply
    assert wa.graph.sent[-1]["to"] == wp.WA_ID
    wa.inbound("Aur transport?")
    assert "STOP" not in wa.graph.texts()[-1]  # only once per conversation

    async def rows(session: AsyncSession) -> tuple[list[Message], list[Followup]]:
        msgs = list((await session.scalars(select(Message).order_by(Message.seq))).all())
        fus = list(
            (await session.scalars(select(Followup).where(Followup.status == "pending"))).all()
        )
        return msgs, fus

    msgs, fus = wa.tenant_q(rows)
    out = [m for m in msgs if m.direction == "out"]
    assert all(m.status == "sent" and m.wa_message_id for m in out)
    assert sorted(f.kind for f in fus) == ["admission_followup_1", "admission_followup_2"]  # reset

    from app.channels.whatsapp.webhook import StatusUpdate
    from app.services.whatsapp import apply_status

    wamid = out[0].wa_message_id
    assert wamid is not None
    for st in ("read", "delivered"):  # out of order: read wins
        wa.run(
            apply_status(
                wa.deps.sessionmaker, wa.tenant, StatusUpdate(f"s:{st}", wa.pnid, wamid, st)
            )
        )

    async def status_of(session: AsyncSession) -> str:
        return str(
            await session.scalar(select(Message.status).where(Message.wa_message_id == wamid))
        )

    assert wa.tenant_q(status_of) == "read"


# --- 6.4 voice notes -------------------------------------------------------------------------


def test_voice_note_transcribed_or_ask_to_type(wa: Env) -> None:
    wa.stt.results = [
        Transcript("Class 3 ki fee kitni hai?", 0.92, "roman_ur", "fake"),
        Transcript("mmm ...", 0.3, None, "fake"),
    ]
    assert wa.inbound(kind="audio", media_id="MEDIA123", mime_type="audio/ogg").startswith(
        "replied"
    )
    assert wa.graph.texts()[-1].startswith("Aap ka voice note mil gaya")
    assert wa.inbound(kind="audio", media_id="MEDIA123").startswith("voice_unclear")
    assert "likh kar" in wa.graph.texts()[-1] or "type" in wa.graph.texts()[-1]

    async def audio_rows(session: AsyncSession) -> list[Message]:
        return list((await session.scalars(select(Message).where(Message.type == "audio"))).all())

    rows = wa.tenant_q(audio_rows)
    assert len(rows) == 2 and rows[0].transcript == "Class 3 ki fee kitni hai?"
    assert rows[0].media_path and rows[0].media_path.endswith(".ogg")
    assert wa.inbound(kind="image", media_id="NOPE").startswith("media_ack")  # no caption


# --- 6.8.1 opt-out ---------------------------------------------------------------------------


def test_opt_out_cancels_followups_and_confirms_once(wa: Env) -> None:
    wa.inbound("Class 3 ki fee?")
    n = len(wa.graph.sent)
    assert wa.inbound("STOP").startswith("opted_out:sent")
    assert len(wa.graph.sent) == n + 1
    assert wa.inbound("stop").startswith("opted_out")
    assert len(wa.graph.sent) == n + 1  # no second confirmation

    async def check(session: AsyncSession) -> tuple[bool, set[str]]:
        c = await session.scalar(select(Contact).where(Contact.wa_id == wp.WA_ID))
        fus = (await session.scalars(select(Followup.status))).all()
        return c is not None and c.opted_out_at is not None, set(fus)

    opted, statuses = wa.tenant_q(check)
    assert opted and statuses == {"cancelled"}


# --- 6.3.2 window ----------------------------------------------------------------------------


def test_window_closed_refuses_free_form(client: TestClient, factory: Factory, wa: Env) -> None:
    wa.inbound("Class 3 ki fee?")

    async def age(session: AsyncSession) -> uuid.UUID:
        conv = await session.scalar(select(Conversation).where(Conversation.channel == "whatsapp"))
        assert conv is not None
        conv.last_inbound_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=30)
        return conv.id

    cid = wa.tenant_q(age)
    staff = auth_headers(client, staff_email(factory, wa.tenant), wa.tenant)
    detail = client.get(f"/api/v1/conversations/{cid}", headers=staff).json()
    assert detail["window_open"] is False and detail["window_expires_at"]
    r = client.post(f"/api/v1/conversations/{cid}/messages", json={"text": "Salam"}, headers=staff)
    assert r.status_code == 409 and "24-hour" in r.json()["detail"]

    async def queue(session: AsyncSession) -> uuid.UUID:
        conv = await session.get(Conversation, cid)
        assert conv is not None
        m = Message(
            conversation_id=cid, direction="out", sender="staff", text="late", status="queued"
        )
        session.add(m)
        await session.flush()
        return m.id

    mid = wa.tenant_q(queue)
    assert wa.run(deliver_message(wa.deps, wa.tenant, mid)) == "failed"

    async def err(session: AsyncSession) -> str | None:
        return await session.scalar(select(Message.error).where(Message.id == mid))

    assert "24-hour" in (wa.tenant_q(err) or "")


# --- 6.6 widget → WhatsApp -------------------------------------------------------------------


def test_session_code_links_widget_contact(client: TestClient, wa: Env) -> None:
    from redis.asyncio import Redis

    async def make_widget_contact(session: AsyncSession) -> uuid.UUID:
        c = Contact(widget_visitor_id="v-link", name="Bilal", preferred_language="roman_ur")
        session.add(c)
        await session.flush()
        session.add(
            Conversation(
                contact_id=c.id,
                channel="widget",
                thread_id=f"{wa.tenant}:{c.id}",
                summary={"text": "Asked about Class 3 fee"},
            )
        )
        return c.id

    widget_contact = wa.tenant_q(make_widget_contact)

    async def go() -> None:
        r = Redis.from_url(wa.settings.redis_url)
        await r.set(
            "widget:wa_code:W1A2B3C",
            json.dumps({"institution_id": str(wa.tenant), "contact_id": str(widget_contact)}),
        )
        wa.deps.redis = r
        wamid = f"wamid.L{uuid.uuid4().hex[:8]}"
        m = InboundMessage(wamid, wa.pnid, wp.WA_ID, None, "text", "Salam! Code: W1A2B3C")
        await process_inbound(wa.deps, wa.tenant, m)
        assert await r.get("widget:wa_code:W1A2B3C") is None  # single use
        await r.aclose()

    asyncio.run(go())

    async def linked(session: AsyncSession) -> Contact | None:
        return await session.scalar(select(Contact).where(Contact.wa_id == wp.WA_ID))

    c = wa.tenant_q(linked)
    assert c is not None and c.name == "Bilal"
    assert c.profile["linked_widget_contact_id"] == str(widget_contact)
    assert c.profile["widget_summary"] == {"text": "Asked about Class 3 fee"}


# --- 6.7 follow-ups + booking reminders + summary --------------------------------------------


def _approve_all(wa: Env, client: TestClient, factory: Factory) -> None:
    admin = auth_headers(client, admin_email(factory, wa.tenant), wa.tenant)
    assert len(client.post("/api/v1/templates/seed", headers=admin).json()) == 33

    async def approve(session: AsyncSession) -> None:
        await session.execute(update(Template).values(status="approved"))

    wa.tenant_q(approve)


def test_followups_gate_and_send(client: TestClient, factory: Factory, wa: Env) -> None:
    _approve_all(wa, client, factory)
    wa.inbound("Class 3 ki fee?")  # schedules +24h / +72h

    async def age_conv(session: AsyncSession) -> None:  # window closed → template path
        await session.execute(
            update(Conversation).values(
                last_inbound_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
            )
        )

    wa.tenant_q(age_conv)
    night = dt.datetime.now(dt.UTC) + dt.timedelta(days=4)
    night = dt.datetime.combine(night.astimezone(PK).date(), dt.time(23, 0), PK)
    while night.weekday() == 4:
        night += dt.timedelta(days=1)
    r1 = wa.run(fu_service.dispatch_due(wa.deps, night, {wa.tenant}))
    assert r1.get("rescheduled") == 2  # quiet hours → next 09:00
    morning = night + dt.timedelta(hours=11)  # 10:00 next day
    n = len(wa.graph.sent)
    r2 = wa.run(fu_service.dispatch_due(wa.deps, morning, {wa.tenant}))
    assert r2.get("sent") == 2
    tpl_sends = [b for b in wa.graph.sent[n:] if b["type"] == "template"]
    assert {b["template"]["name"] for b in tpl_sends} == {
        "admission_followup_1_ru",
        "admission_followup_2_ru",
    }
    params = tpl_sends[0]["template"]["components"][0]["parameters"]
    assert params[0]["text"] == "Ayesha"

    async def more(session: AsyncSession) -> uuid.UUID:
        c = await session.scalar(select(Contact).where(Contact.wa_id == wp.WA_ID))
        assert c is not None
        for _ in range(2):
            session.add(Followup(contact_id=c.id, kind="lead_followup", due_at=morning))
        return c.id

    wa.tenant_q(more)
    r3 = wa.run(fu_service.dispatch_due(wa.deps, morning + dt.timedelta(minutes=5), {wa.tenant}))
    assert r3.get("sent") == 1 and r3.get("rescheduled") == 1  # weekly cap of 3

    async def human(session: AsyncSession) -> None:
        await session.execute(update(Conversation).values(mode="human"))
        await session.execute(
            update(Followup).where(Followup.status == "pending").values(due_at=morning)
        )

    wa.tenant_q(human)
    r4 = wa.run(fu_service.dispatch_due(wa.deps, morning + dt.timedelta(minutes=10), {wa.tenant}))
    assert r4.get("cancelled") == 1


def test_booking_reminder_and_daily_summary(client: TestClient, factory: Factory, wa: Env) -> None:
    _approve_all(wa, client, factory)
    wa.inbound("Visit book karna hai")
    now = dt.datetime.combine(dt.date.today() + dt.timedelta(days=3), dt.time(10, 30), PK)
    while now.weekday() == 4:
        now += dt.timedelta(days=1)
    starts = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(11, 0), PK)

    async def book(session: AsyncSession) -> None:
        c = await session.scalar(select(Contact).where(Contact.wa_id == wp.WA_ID))
        assert c is not None
        slot = Slot(
            kind="visit",
            starts_at=starts,
            ends_at=starts + dt.timedelta(hours=1),
            capacity=5,
            booked_count=1,
            location="Main campus",
        )
        session.add(slot)
        await session.flush()
        session.add(Booking(slot_id=slot.id, contact_id=c.id, code="V7K2Q9", status="booked"))

    wa.tenant_q(book)
    n = len(wa.graph.sent)
    counts = wa.run(fu_service.dispatch_due(wa.deps, now, {wa.tenant}))
    assert counts.get("reminders_scheduled") == 1 and counts.get("sent", 0) >= 1
    texts = [b for b in wa.graph.sent[n:] if b["type"] == "template"]
    assert any(b["template"]["name"] == "visit_reminder_ru" for b in texts)
    again = wa.run(fu_service.dispatch_due(wa.deps, now + dt.timedelta(minutes=1), {wa.tenant}))
    assert again.get("reminders_scheduled", 0) == 0  # once per booking

    async def summary(session: AsyncSession) -> dict[str, Any]:
        inst = await session.get(Institution, wa.tenant)
        assert inst is not None
        return await build_summary(session, inst, dt.datetime.now(PK).date())

    s = wa.tenant_q(summary)
    assert s["conversations"] >= 1 and s["top_questions"]

    async def numbers(session: AsyncSession) -> None:
        inst = await session.get(Institution, wa.tenant)
        assert inst is not None
        inst.settings = {**inst.settings, "daily_summary": {"numbers": ["+92 300 7654321"]}}

    wa.tenant_q(numbers)
    assert wa.run(send_daily_summaries(wa.deps)) >= 1
    assert wa.graph.sent[-1]["to"] == "923007654321"
    assert wa.graph.sent[-1]["template"]["name"] == "daily_summary_ru"


# --- 6.5 templates API -----------------------------------------------------------------------


def test_templates_api_submit_status_sync(client: TestClient, factory: Factory, wa: Env) -> None:
    admin = auth_headers(client, admin_email(factory, wa.tenant), wa.tenant)
    staff = auth_headers(client, staff_email(factory, wa.tenant), wa.tenant)
    url = "/api/v1/templates"
    assert len(client.post(f"{url}/seed", headers=admin).json()) == 33
    assert client.post(f"{url}/seed", headers=admin).json() == []  # idempotent
    assert client.post(f"{url}/seed", headers=staff).status_code == 403
    bad = {"name": "Bad Name", "language": "en", "body": "hello"}
    assert client.post(url, json=bad, headers=admin).status_code == 422
    new = client.post(
        url,
        json={
            "name": "open_day",
            "language": "ur",
            "body": "محترم {{name}}، اوپن ڈے ہفتہ کو ہے۔",
            "examples": ["Ayesha"],
        },
        headers=admin,
    )
    assert new.status_code == 201 and new.json()["variables"] == ["name"]
    tid = new.json()["id"]
    sub = client.post(f"{url}/{tid}/submit", headers=admin)
    assert sub.status_code == 200 and sub.json()["status"] == "pending"
    sent = wa.graph.submitted[-1]
    assert sent["name"] == "open_day" and sent["language"] == "ur"
    assert sent["components"][0]["text"].startswith("محترم {{1}}")
    assert (
        client.patch(f"{url}/{tid}", json={"body": "x {{name}} y"}, headers=admin).status_code
        == 409
    )

    from app.channels.whatsapp.webhook import parse_payload
    from app.services.whatsapp import apply_template_status

    (item,) = parse_payload(
        _swap_pnid(wp.template_status("open_day", "ur", "APPROVED", "tpl1"), wa.pnid, wa.waba)
    )
    assert wa.run(apply_template_status(wa.deps.sessionmaker, wa.tenant, item)) == "approved"  # type: ignore[arg-type]
    rows = {(t["name"], t["language"]): t for t in client.get(url, headers=staff).json()}
    assert rows[("open_day", "ur")]["status"] == "approved"

    wa.graph.remote_templates = [
        {
            "id": "r1",
            "name": "visit_reminder_ru",
            "language": "en",
            "status": "REJECTED",
            "rejected_reason": "INVALID_FORMAT",
        }
    ]
    synced = client.post(f"{url}/sync", headers=admin).json()
    assert synced == {"updated": 1, "remote": 1}
    rows = {(t["name"], t["language"]): t for t in client.get(url, headers=staff).json()}
    assert rows[("visit_reminder", "roman_ur")]["status"] == "rejected"
    assert rows[("visit_reminder", "roman_ur")]["rejected_reason"] == "INVALID_FORMAT"


def _member(factory: Factory, tenant: uuid.UUID, role: str) -> str:
    from app.services import provisioning
    from tests.support import PASSWORD

    email = f"{role}-{uuid.uuid4().hex[:6]}@raabta-test.pk"

    async def make(session: AsyncSession) -> str:
        user = await provisioning.upsert_user(session, email=email, name=role, password=PASSWORD)
        await provisioning.upsert_membership(
            session, institution_id=tenant, user_id=user.id, role=role
        )
        return email

    return asyncio.run(as_admin(factory.settings, make))


def staff_email(factory: Factory, tenant: uuid.UUID) -> str:
    return _member(factory, tenant, "staff")


def admin_email(factory: Factory, tenant: uuid.UUID) -> str:
    return _member(factory, tenant, "admin")
