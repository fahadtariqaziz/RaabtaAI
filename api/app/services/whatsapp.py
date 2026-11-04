"""WhatsApp channel service (steps 6.2–6.6): webhook event intake, inbound processing (media,
voice → STT, widget-session linking) into `run_inbound`, and the single outbound delivery path
(`deliver_message`) that enforces the 24h window and the first-reply privacy line.

Every outbound WhatsApp message is first written as a `queued` row (AI reply, staff reply,
static reply, booking note) and then delivered here — so the inbox shows exactly what was sent,
and failures carry a reason (`messages.error`)."""

import dataclasses
import datetime as dt
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.inbound import InboundEvent, run_inbound
from app.agent.phrases import phrase
from app.agent.runtime import AgentRuntime
from app.channels.stt import LOW_CONFIDENCE, SpeechToTextError, SpeechToTextProvider
from app.channels.whatsapp.client import WhatsAppClient, WhatsAppError
from app.channels.whatsapp.compose import compose
from app.channels.whatsapp.templates import TemplateError, meta_language, meta_name, render
from app.channels.whatsapp.webhook import (
    InboundMessage,
    StatusUpdate,
    TemplateStatus,
    WebhookItem,
    status_advances,
)
from app.channels.whatsapp.window import free_form_allowed
from app.core.tenancy import admin_session, tenant_session
from app.kb.blobstore import BlobStore
from app.kb.text import detect_lang
from app.models.conversations import Contact, Conversation, Followup, Message
from app.models.core import Institution, WebhookEvent
from app.models.templates import Template
from app.services.conversations import add_message, get_or_create_contact, open_conversation

log = logging.getLogger(__name__)

PROVIDER = "whatsapp"
SESSION_CODE = re.compile(r"\b(W[0-9A-F]{6})\b")
NO_REPLY_FOLLOWUPS = (("admission_followup_1", 24), ("admission_followup_2", 72))
# G16: media we keep (anything else is acknowledged but not stored).
MEDIA_TYPES = {
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/amr": "amr",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}
MESSAGE_TYPE = {"audio": "audio", "image": "image", "document": "document"}
DeliverStatus = Literal["sent", "failed", "retry", "skipped"]


@dataclass
class WhatsAppDeps:
    sessionmaker: async_sessionmaker[AsyncSession]
    client: WhatsAppClient | None
    blobstore: BlobStore
    redis: Any
    agent: Callable[[], Awaitable[AgentRuntime]]
    stt: Callable[[], SpeechToTextProvider] | None = None
    enqueue: Callable[..., Awaitable[Any]] | None = None  # arq enqueue_job (retries)


# --- webhook intake (step 6.2.1) ------------------------------------------------------------


async def institution_for(
    session: AsyncSession, *, phone_number_id: str | None = None, waba_id: str | None = None
) -> uuid.UUID | None:
    """Tenant lookup by Meta ids (platform table; caller holds an admin session)."""
    if phone_number_id:
        where = Institution.wa_phone_number_id == phone_number_id
    elif waba_id:
        where = Institution.waba_id == waba_id
    else:
        return None
    return await session.scalar(select(Institution.id).where(where).limit(1))


async def record_events(
    sessionmaker: async_sessionmaker[AsyncSession], items: list[WebhookItem]
) -> list[uuid.UUID]:
    """Insert one `webhook_events` row per item (unique provider+event_id); returns the ids of
    rows that are new and belong to a known institution → to enqueue. Duplicates are no-ops."""
    new: list[uuid.UUID] = []
    async with admin_session(sessionmaker) as session:
        for item in items:
            if isinstance(item, TemplateStatus):
                inst = await institution_for(session, waba_id=item.waba_id)
            else:
                inst = await institution_for(session, phone_number_id=item.phone_number_id)
            row_id = await session.scalar(
                insert(WebhookEvent)
                .values(
                    provider=PROVIDER,
                    event_id=item.event_id,
                    institution_id=inst,
                    payload=dataclasses.asdict(item),
                    status="received" if inst else "ignored",
                    error=None if inst else "unknown phone_number_id / waba_id",
                )
                .on_conflict_do_nothing(index_elements=["provider", "event_id"])
                .returning(WebhookEvent.id)
            )
            if row_id is not None and inst is not None:
                new.append(row_id)
    return new


def item_from_payload(payload: dict[str, Any]) -> WebhookItem:
    data = dict(payload)
    tag = data.pop("kind_tag", None)
    if tag == "message":
        return InboundMessage(**data)
    if tag == "status":
        return StatusUpdate(**data)
    if tag == "template_status":
        return TemplateStatus(**data)
    raise ValueError(f"unknown webhook item {tag!r}")


async def process_event(deps: WhatsAppDeps, event_id: uuid.UUID) -> str:
    """Worker entry (step 6.2.4): one stored webhook item → its handler; marks the row."""
    async with admin_session(deps.sessionmaker) as session:
        ev = await session.get(WebhookEvent, event_id)
        if ev is None or ev.status != "received" or ev.institution_id is None:
            return "skipped"
        institution_id, payload = ev.institution_id, dict(ev.payload)
    outcome, error = "processed", None
    try:
        item = item_from_payload(payload)
        if isinstance(item, InboundMessage):
            outcome = await process_inbound(deps, institution_id, item)
        elif isinstance(item, StatusUpdate):
            outcome = await apply_status(deps.sessionmaker, institution_id, item)
        else:
            outcome = await apply_template_status(deps.sessionmaker, institution_id, item)
    except Exception as exc:  # recorded for replay; the type only (no payload/PII in logs)
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
        log.exception("whatsapp event %s failed", event_id)
    async with admin_session(deps.sessionmaker) as session:
        await session.execute(
            update(WebhookEvent)
            .where(WebhookEvent.id == event_id)
            .values(
                status="failed" if error else "processed",
                error=error,
                processed_at=func.now(),
            )
        )
    return "failed" if error else outcome


# --- statuses (step 6.3.3) & template statuses (6.5.2) --------------------------------------


async def apply_status(
    sessionmaker: async_sessionmaker[AsyncSession], institution_id: uuid.UUID, s: StatusUpdate
) -> str:
    async with tenant_session(sessionmaker, institution_id) as session:
        msg = await session.scalar(select(Message).where(Message.wa_message_id == s.wa_message_id))
        if msg is None:
            return "unknown_message"
        if not status_advances(msg.status, s.status):
            return "stale"
        msg.status = s.status
        if s.status == "failed":
            err = s.errors[0] if s.errors else {}
            msg.error = f"{err.get('code', '')} {err.get('title') or err.get('message') or ''}"[
                :300
            ].strip()
        return s.status


TEMPLATE_STATUS_MAP = {
    "APPROVED": "approved",
    "REJECTED": "rejected",
    "PAUSED": "paused",
    "DISABLED": "disabled",
    "PENDING": "pending",
    "IN_APPEAL": "pending",
    "PENDING_DELETION": "disabled",
    "DELETED": "disabled",
    "FLAGGED": "approved",  # still sendable; quality warning
    "REINSTATED": "approved",
}


async def apply_template_status(
    sessionmaker: async_sessionmaker[AsyncSession], institution_id: uuid.UUID, t: TemplateStatus
) -> str:
    status = TEMPLATE_STATUS_MAP.get(t.status)
    if status is None:
        return "ignored"
    async with tenant_session(sessionmaker, institution_id) as session:
        rows = (await session.scalars(select(Template))).all()
        hit = [
            r
            for r in rows
            if (t.template_id and r.meta_template_id == t.template_id)
            or (
                t.name == meta_name(r)
                and (t.language or "") in (meta_language(r.language), "")
                and not r.meta_template_id
            )
        ]
        for r in hit:
            r.status = status
            r.rejected_reason = t.reason if status == "rejected" else None
            if t.template_id:
                r.meta_template_id = t.template_id
        return status if hit else "unknown_template"


# --- inbound (steps 6.2.2–6.2.4, 6.4, 6.6) ----------------------------------------------------


async def _store_media(
    deps: WhatsAppDeps, institution_id: uuid.UUID, m: InboundMessage
) -> tuple[str | None, bytes | None, str | None]:
    if deps.client is None or not m.media_id:
        return None, None, None
    data, mime = await deps.client.download_media(m.media_id)
    base = mime.split(";")[0].strip().lower()
    ext = MEDIA_TYPES.get(base)
    if ext is None:
        return None, None, base
    key = f"wa/{institution_id}/{m.event_id[-40:].replace('/', '_')}.{ext}"
    await deps.blobstore.put(key, data)
    return key, data, base


async def link_widget_session(
    redis: Any, session: AsyncSession, institution_id: uuid.UUID, contact: Contact, text: str
) -> bool:
    """Step 6.6: a "Continue on WhatsApp" message carries `W` + 6 hex; the widget stored
    code → (institution, widget contact) in Redis. Link the two contacts (profile + summary
    carried over) so the WhatsApp thread knows what was said on the website."""
    if redis is None:
        return False
    m = SESSION_CODE.search(text.upper())
    if not m:
        return False
    raw = await redis.get(f"widget:wa_code:{m.group(1)}")
    if not raw:
        return False
    info = json.loads(raw)
    if info.get("institution_id") != str(institution_id):
        return False
    widget_contact = await session.get(Contact, uuid.UUID(info["contact_id"]))
    if widget_contact is None or widget_contact.id == contact.id:
        return False
    last_widget = await session.scalar(
        select(Conversation)
        .where(Conversation.contact_id == widget_contact.id, Conversation.channel == "widget")
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    profile = dict(widget_contact.profile or {}) | dict(contact.profile or {})
    profile["linked_widget_contact_id"] = str(widget_contact.id)
    if last_widget is not None and last_widget.summary:
        profile["widget_summary"] = last_widget.summary
    contact.profile = profile
    contact.name = contact.name or widget_contact.name
    contact.preferred_language = contact.preferred_language or widget_contact.preferred_language
    await redis.delete(f"widget:wa_code:{m.group(1)}")
    return True


async def _cancel_no_reply_followups(session: AsyncSession, contact_id: uuid.UUID) -> None:
    await session.execute(
        update(Followup)
        .where(
            Followup.contact_id == contact_id,
            Followup.status.in_(("pending", "held")),
            Followup.kind.in_([k for k, _ in NO_REPLY_FOLLOWUPS]),
        )
        .values(status="cancelled")
    )


async def schedule_no_reply_followups(
    session: AsyncSession, contact_id: uuid.UUID, now: dt.datetime
) -> None:
    """Step 6.7.1: after an AI reply, follow up at +24h / +72h unless the parent writes again
    (any inbound cancels them first)."""
    await _cancel_no_reply_followups(session, contact_id)
    for kind, hours in NO_REPLY_FOLLOWUPS:
        session.add(
            Followup(
                contact_id=contact_id,
                kind=kind,
                template_name=kind,
                due_at=now + dt.timedelta(hours=hours),
            )
        )


async def process_inbound(deps: WhatsAppDeps, institution_id: uuid.UUID, m: InboundMessage) -> str:
    now = dt.datetime.now(dt.UTC)
    media_path: str | None = None
    transcript_text: str | None = None
    voice_unclear = False
    text = m.text or ""
    if m.kind in MESSAGE_TYPE:
        try:
            media_path, data, mime = await _store_media(deps, institution_id, m)
        except WhatsAppError as exc:
            log.warning("media download failed: %s", exc)
            data, mime = None, None
        if m.kind == "audio":
            voice_unclear = True
            if data is not None and mime is not None and deps.stt is not None:
                try:
                    tr = await deps.stt().transcribe(data, mime)
                except Exception as exc:  # provider down / key missing → ask to type
                    log.warning("stt failed: %s", type(exc).__name__)
                    if not isinstance(exc, SpeechToTextError | WhatsAppError):
                        log.debug("stt error detail", exc_info=True)
                else:
                    transcript_text = tr.text or None
                    voice_unclear = not tr.text or tr.confidence < LOW_CONFIDENCE
                    if not voice_unclear:
                        text = tr.text

    async with tenant_session(deps.sessionmaker, institution_id) as session:
        contact = await get_or_create_contact(session, wa_id=m.wa_id, name=m.name)
        await _cancel_no_reply_followups(session, contact.id)
        if text:
            await link_widget_session(deps.redis, session, institution_id, contact, text)

    rt = await deps.agent()
    event = InboundEvent(
        institution_id=institution_id,
        channel="whatsapp",
        text=text,
        wa_id=m.wa_id,
        name=m.name,
        wa_message_id=m.event_id,
        message_type=MESSAGE_TYPE.get(m.kind, "text"),
        media_path=media_path,
        transcript=transcript_text,
        voice_unclear=voice_unclear,
        now=now,
    )
    result = await run_inbound(rt.deps, rt.graph, event)
    if result.message_id is None:
        return result.status
    prefix = (
        phrase("voice_ack", result.language or "roman_ur")
        if m.kind == "audio" and result.status == "replied"
        else None
    )
    status = await deliver_message(
        deps,
        institution_id,
        uuid.UUID(result.message_id),
        quick_replies=result.quick_replies,
        prefix=prefix,
        language=result.language,
    )
    if status == "retry":
        await enqueue_delivery(deps.enqueue, institution_id, uuid.UUID(result.message_id), 30)
    if result.status == "replied" and result.contact_id is not None:
        async with tenant_session(deps.sessionmaker, institution_id) as session:
            conv = await session.get(Conversation, result.conversation_id)
            if conv is not None and conv.module == "admissions":
                await schedule_no_reply_followups(session, result.contact_id, now)
    return f"{result.status}:{status}"


# --- outbound (step 6.3) ----------------------------------------------------------------------


async def enqueue_delivery(
    enqueue: Callable[..., Awaitable[Any]] | None,
    institution_id: uuid.UUID,
    message_id: uuid.UUID,
    defer: int = 0,
) -> None:
    """Queue `deliver_message_job` (arq `enqueue_job`; None = no queue, e.g. tests)."""
    if enqueue is not None:
        await enqueue(
            "deliver_message_job", str(institution_id), str(message_id), _defer_by=defer or None
        )


async def _first_reply(session: AsyncSession, conv: Conversation, msg: Message) -> bool:
    prior = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.direction == "out",
            Message.type != "note",
            Message.status.in_(("sent", "delivered", "read")),
            Message.id != msg.id,
        )
    )
    return not prior


def _language(contact: Contact, text: str, hint: str | None) -> str:
    return hint or contact.preferred_language or detect_lang(text)


async def deliver_message(
    deps: WhatsAppDeps,
    institution_id: uuid.UUID,
    message_id: uuid.UUID,
    *,
    quick_replies: list[str] | None = None,
    prefix: str | None = None,
    language: str | None = None,
    now: dt.datetime | None = None,
    allow_retry: bool = True,
) -> DeliverStatus:
    """Send one queued outbound row. Free-form only inside the 24h window (6.3.2); outside it
    the row fails with a reason (staff must use a template). A retryable Graph error leaves the
    row queued and returns "retry" (caller re-queues `deliver_message_job`)."""
    now = now or dt.datetime.now(dt.UTC)
    async with tenant_session(deps.sessionmaker, institution_id) as session:
        msg = await session.get(Message, message_id)
        if msg is None or msg.status != "queued" or msg.direction != "out" or msg.type == "note":
            return "skipped"
        conv = await session.get(Conversation, msg.conversation_id)
        if conv is None or conv.channel != "whatsapp":
            return "skipped"
        contact = await session.get(Contact, conv.contact_id)
        inst = await session.get(Institution, institution_id)
        if contact is None or inst is None:
            return "skipped"

        def fail(reason: str) -> DeliverStatus:
            msg.status, msg.error = "failed", reason
            return "failed"

        if deps.client is None or not inst.wa_phone_number_id:
            return fail("WhatsApp number not connected")
        if not contact.wa_id:
            return fail("contact has no WhatsApp number")
        if not free_form_allowed(conv.last_inbound_at, now):
            return fail("outside the 24-hour window — send an approved template instead")
        text = msg.text or ""
        lang = _language(contact, text, language)
        if prefix:
            text = f"{prefix}\n\n{text}"
        if msg.sender in ("ai", "system") and await _first_reply(session, conv, msg):
            text = f"{text}\n\n{phrase('privacy', lang)}"  # step 6.8.4 / PLAN §21
        out = compose(text, quick_replies)
        pnid, to = inst.wa_phone_number_id, contact.wa_id
        try:
            first_id: str | None = None
            for i, part in enumerate(out.parts):
                last = i == len(out.parts) - 1
                if last and out.buttons:
                    res = await deps.client.send_buttons(pnid, to, part, out.buttons)
                elif last and out.list_rows:
                    button = phrase("options", lang)
                    res = await deps.client.send_list(pnid, to, part, button, out.list_rows)
                else:
                    res = await deps.client.send_text(pnid, to, part)
                first_id = first_id or res.wa_message_id
                if len(out.parts) > 1 and i == 0:
                    msg.wa_message_id = first_id  # partial progress survives a later failure
                    await session.flush()
        except WhatsAppError as exc:
            if exc.retryable and allow_retry:
                msg.error = f"retrying: {exc}"[:300]
                return "retry"
            return fail(str(exc)[:300])
        msg.text, msg.wa_message_id, msg.status, msg.error = text, first_id, "sent", None
        return "sent"


async def send_template(
    deps: WhatsAppDeps,
    session: AsyncSession,
    *,
    contact: Contact,
    template_name: str,
    values: dict[str, Any],
    conversation: Conversation | None = None,
    sender: str = "system",
    now: dt.datetime | None = None,
) -> Message:
    """Render + send an approved template to a contact (follow-ups, reminders). Inside the 24h
    window the same rendered text goes out free-form (free, and works before Meta approval).
    The row is written either way: `sent` or `failed` with the reason."""
    now = now or dt.datetime.now(dt.UTC)
    inst = await session.get(Institution, session.info["institution_id"])
    if inst is None:
        raise LookupError("institution not found")
    lang = contact.preferred_language or "roman_ur"
    candidates = (
        await session.scalars(select(Template).where(Template.name == template_name))
    ).all()
    by_lang = {t.language: t for t in candidates}
    tpl = by_lang.get(lang) or by_lang.get("roman_ur") or by_lang.get("en")
    conv = conversation or await open_conversation(session, contact, channel="whatsapp")
    if tpl is None:
        raise TemplateError(f"template {template_name!r} not found")
    text, params = render(tpl, values)
    msg = await add_message(
        session,
        conv,
        direction="out",
        sender=sender,
        type="template",
        text=text,
        template_name=template_name,
    )
    if deps.client is None or not inst.wa_phone_number_id or not contact.wa_id:
        msg.status, msg.error = "failed", "WhatsApp number not connected"
        return msg
    try:
        if free_form_allowed(conv.last_inbound_at, now):
            msg.type = "text"  # inside the window: plain text, not billed as a template
            res = await deps.client.send_text(inst.wa_phone_number_id, contact.wa_id, text)
        elif tpl.status != "approved":
            msg.status, msg.error = "failed", f"template {meta_name(tpl)} is not approved yet"
            return msg
        else:
            res = await deps.client.send_template(
                inst.wa_phone_number_id,
                contact.wa_id,
                meta_name(tpl),
                meta_language(tpl.language),
                params,
            )
    except WhatsAppError as exc:
        msg.status, msg.error = "failed", str(exc)[:300]
        return msg
    msg.status, msg.wa_message_id = "sent", res.wa_message_id
    return msg
