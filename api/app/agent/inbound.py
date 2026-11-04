"""`run_inbound(event)` — the single entrypoint for widget and WhatsApp turns (step 3.5.4).

Deterministic pre-graph steps (PLAN §6.1 ingest): dedupe (Redis), contact + conversation, store
the inbound message, opt-out/opt-in keywords (G7), human-mode gate (no AI reply while staff own
the chat), per-contact rate limit (G8), per-conversation daily cap (G13), a per-thread lock;
then the graph runs on thread `institution:contact`. `resume_after_handoff` = "Return to AI"."""

import datetime as dt
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import HISTORY_KEEP, AgentDeps
from app.agent.guards import (
    allow_contact_message,
    first_delivery,
    is_opt_in,
    is_opt_out,
    take_daily_turn,
)
from app.agent.phrases import phrase
from app.agent.state import turn_input
from app.core.tenancy import tenant_session
from app.kb.text import detect_lang
from app.models.conversations import Contact, Conversation, Message
from app.models.core import Institution
from app.models.facts import FeeItem, KeyDate
from app.services.conversations import add_message, get_or_create_contact, open_conversation

Status = Literal[
    "replied",
    "duplicate",
    "human_mode",
    "escalated",
    "opted_out",
    "opted_in",
    "rate_limited",
    "daily_cap",
]
CTA_TEXT = {
    "school": "invite the parent for a campus visit",
    "college": "offer a counselling session with the admissions office",
    "university": "point to the online application and its deadline",
}
DETAIL_KEYS_SKIP = {"cta", "escalation", "academic_year"}


@dataclass
class InboundEvent:
    institution_id: uuid.UUID
    channel: Literal["widget", "whatsapp"]
    text: str
    widget_visitor_id: str | None = None
    wa_id: str | None = None
    name: str | None = None
    client_msg_id: str | None = None
    wa_message_id: str | None = None
    now: dt.datetime | None = None  # injected clock (tests/evals); default = now


@dataclass
class TurnResult:
    status: Status
    reply: str | None = None
    reply_kind: str | None = None
    language: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    quick_replies: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = field(default_factory=list)
    check: dict[str, Any] | None = None
    route: dict[str, Any] | None = None
    guard: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    contact_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    message_id: str | None = None

    @property
    def cost_usd(self) -> Decimal:
        return sum((Decimal(r.get("cost_usd") or "0") for r in self.runs), Decimal("0"))


def escalation_hit(settings: dict[str, Any], text: str) -> bool:
    """Admin-configured escalation keywords (settings.escalation.keywords, step 5.8) → human."""
    keywords = (settings.get("escalation") or {}).get("keywords") or []
    low = text.casefold()
    return any(isinstance(k, str) and k.strip() and k.strip().casefold() in low for k in keywords)


def pg_url(database_url: str) -> str:
    """SQLAlchemy asyncpg URL → libpq URL for psycopg (LangGraph checkpointer)."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def postgres_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    """Checkpointer on its own small psycopg pool. Tables come from migration 0003 (no
    `setup()` at runtime)."""
    async with AsyncExitStack() as stack:
        pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            pg_url(database_url),
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await pool.open()
        stack.push_async_callback(pool.close)
        yield AsyncPostgresSaver(pool)


async def _academic_year(session: AsyncSession, settings: dict[str, Any]) -> str | None:
    if settings.get("academic_year"):
        return str(settings["academic_year"])
    years: Counter[str] = Counter()
    for model in (FeeItem, KeyDate):
        rows = await session.scalars(
            select(model.academic_year).where(
                model.status == "approved", model.academic_year.is_not(None)
            )
        )
        years.update(y for y in rows.all() if y)
    return min(years, key=lambda y: (-years[y], y)) if years else None


async def tenant_view(session: AsyncSession, institution_id: uuid.UUID) -> dict[str, Any]:
    inst = await session.get(Institution, institution_id)
    if inst is None:
        raise LookupError("institution not found")
    settings = dict(inst.settings or {})
    details = {
        k: str(v)
        for k, v in settings.items()
        if k not in DETAIL_KEYS_SKIP and isinstance(v, str | int | float)
    }
    return {
        "name": inst.name,
        "type": inst.type,
        "city": inst.city,
        "timezone": inst.timezone,
        "languages": list(inst.languages or []),
        "facts_version": inst.facts_version,
        "academic_year": await _academic_year(session, settings),
        "cta": CTA_TEXT.get(inst.type, "offer to connect them with the office"),
        "details": details,
    }


def contact_view(contact: Contact) -> dict[str, Any]:
    profile = dict(contact.profile or {})
    return {
        "preferred_language": contact.preferred_language,
        "verified": bool((contact.verified or {}).get("verified")),
        "profile_view": {
            "name": contact.name,
            "preferred_language": contact.preferred_language,
            "student_name": profile.get("student_name"),
            "student_class": profile.get("student_class"),
        },
    }


async def _static_reply(
    session: AsyncSession, conv: Conversation, text: str, status: Status, language: str
) -> TurnResult:
    msg = await add_message(session, conv, direction="out", sender="system", text=text)
    return TurnResult(
        status=status,
        reply=text,
        reply_kind="static",
        language=language,
        contact_id=conv.contact_id,
        conversation_id=conv.id,
        message_id=str(msg.id),
    )


async def run_inbound(
    deps: AgentDeps, graph: CompiledStateGraph[Any, Any, Any, Any], event: InboundEvent
) -> TurnResult:
    now = event.now or dt.datetime.now(dt.UTC)
    if not await first_delivery(
        deps.redis, event.institution_id, event.wa_message_id or event.client_msg_id
    ):
        return TurnResult(status="duplicate")
    language = detect_lang(event.text)
    async with tenant_session(deps.sessionmaker, event.institution_id) as session:
        contact = await get_or_create_contact(
            session, wa_id=event.wa_id, widget_visitor_id=event.widget_visitor_id, name=event.name
        )
        conv = await open_conversation(session, contact, channel=event.channel)
        await add_message(
            session,
            conv,
            direction="in",
            sender="contact",
            text=event.text,
            client_msg_id=event.client_msg_id,
            wa_message_id=event.wa_message_id,
        )
        lang = contact.preferred_language or language
        if is_opt_out(event.text):
            contact.opted_out_at = now
            return await _static_reply(session, conv, phrase("opted_out", lang), "opted_out", lang)
        if contact.opted_out_at is not None and is_opt_in(event.text):
            contact.opted_out_at = None
        if conv.mode == "human":
            return TurnResult(status="human_mode", contact_id=contact.id, conversation_id=conv.id)
        inst = await session.get(Institution, event.institution_id)
        if inst is not None and escalation_hit(inst.settings or {}, event.text):
            conv.mode, conv.status, conv.flagged = "human", "pending", True
            return await _static_reply(session, conv, phrase("handoff", lang), "escalated", lang)
        if not await allow_contact_message(deps.redis, event.institution_id, contact.id, now):
            return await _static_reply(
                session, conv, phrase("rate_limited", lang), "rate_limited", lang
            )
        tz = ZoneInfo((await session.get(Institution, event.institution_id)).timezone)  # type: ignore[union-attr]
        if not await take_daily_turn(deps.redis, conv.id, now.astimezone(tz).date()):
            return await _static_reply(session, conv, phrase("daily_cap", lang), "daily_cap", lang)
        tenant = await tenant_view(session, event.institution_id)
        cview = contact_view(contact)
        contact_id, conv_id, thread_id = contact.id, conv.id, conv.thread_id
    state = turn_input(
        institution_id=str(event.institution_id),
        contact_id=str(contact_id),
        conversation_id=str(conv_id),
        channel=event.channel,
        now=now.isoformat(),
        inbound={"text": event.text},
        tenant=tenant,
        contact=cview,
    )
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    lock = (
        deps.redis.lock(f"lock:thread:{thread_id}", timeout=180, blocking_timeout=60)
        if deps.redis is not None
        else None
    )
    if lock is not None:
        await lock.acquire()
    try:
        final: dict[str, Any] = await graph.ainvoke(state, config)
    finally:
        if lock is not None:
            await lock.release()
    return TurnResult(
        status="replied",
        reply=final.get("final"),
        reply_kind=final.get("reply_kind"),
        language=final.get("language"),
        citations=final.get("citations", []),
        quick_replies=final.get("quick_replies", []),
        tool_calls=final.get("tool_calls", []),
        tool_outputs=final.get("tool_outputs", []),
        check=final.get("check"),
        route=final.get("route"),
        guard=final.get("guard"),
        events=final.get("events", []),
        sources=final.get("sources", []),
        runs=final.get("runs", []),
        contact_id=contact_id,
        conversation_id=conv_id,
        message_id=final.get("outbound_message_id"),
    )


async def resume_after_handoff(
    deps: AgentDeps,
    graph: CompiledStateGraph[Any, Any, Any, Any],
    institution_id: uuid.UUID,
    conversation_id: uuid.UUID,
    staff_note: str | None = None,
) -> None:
    """ "Return to AI": mode=ai, and resume the paused thread with the staff note (if any) so
    the next turn's context knows what staff promised."""
    async with tenant_session(deps.sessionmaker, institution_id) as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise LookupError("conversation not found")
        conv.mode, conv.status = "ai", "open"
        thread_id = conv.thread_id
        staff_msgs = (
            await session.scalars(
                select(Message.text)
                .where(Message.conversation_id == conversation_id, Message.sender == "staff")
                .order_by(Message.seq.desc())
                .limit(3)
            )
        ).all()
    note = staff_note or " / ".join(t for t in reversed(staff_msgs) if t) or None
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    if snapshot.next:  # paused in await_staff
        await graph.ainvoke(Command(resume={"staff_note": note}), config)
    elif note and snapshot.values:  # manual takeover (thread not paused): carry the note over
        values = snapshot.values
        history = [*values.get("history", []), {"role": "staff", "text": note}]
        await graph.aupdate_state(
            config,
            {
                "staff_notes": [*values.get("staff_notes", []), note],
                "history": history[-HISTORY_KEEP:],
            },
            as_node="await_staff",
        )
