"""`/api/v1/conversations` — live inbox with human takeover (PLAN §6.1, §14, §17; step 5.4).

Staff+ only. Takeover → `mode=human` (the inbound gate stores parent messages without an AI reply);
staff replies are queued outbound messages (widget polls `/widget/sessions/{id}/updates`, WhatsApp
sender in 6.3). "Return to AI" resumes the LangGraph thread with the staff note so the next AI
turn knows what staff said. Internal notes are `type=note` and never leave the inbox.
`GET /conversations/events` is a fetch-SSE stream of changed conversation ids (DB-polled → works
across API processes without extra plumbing)."""

import asyncio
import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, func, or_, select

from app.agent.inbound import resume_after_handoff
from app.api.deps import RedisDep, SessionDep, StaffCtx, audit_mutations
from app.channels.whatsapp.window import free_form_allowed, window_expires_at
from app.core.tenancy import TenantContext, tenant_session
from app.models.conversations import Booking, Contact, Conversation, Lead, Message, Slot
from app.models.core import Membership, User
from app.services.audit import audit_ctx
from app.services.conversations import add_message
from app.services.whatsapp import enqueue_delivery

router = APIRouter(prefix="/conversations", tags=["conversations"], dependencies=[audit_mutations])
SANDBOX_PREFIX = "sandbox-"  # KB playground contacts (5.7.4) never show in the inbox
EVENTS_TICK_S = 2.0
EVENTS_MAX_S = 300  # client reconnects; keeps proxies and workers healthy


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str | None
    phone: str | None
    wa_id: str | None
    preferred_language: str | None
    opted_out_at: dt.datetime | None
    created_at: dt.datetime


class LastMessage(BaseModel):
    text: str | None
    sender: str
    type: str
    created_at: dt.datetime


class ConversationRow(BaseModel):
    id: uuid.UUID
    channel: str
    module: str
    mode: str
    status: str
    flagged: bool
    assigned_user_id: uuid.UUID | None
    contact: ContactOut
    last_message: LastMessage | None
    awaiting_reply: bool
    last_inbound_at: dt.datetime | None
    updated_at: dt.datetime


class LeadBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    student_name: str | None
    guardian_name: str | None
    phone: str | None
    interest: str | None


class BookingBrief(BaseModel):
    id: uuid.UUID
    code: str
    status: str
    kind: str
    starts_at: dt.datetime


class ConversationDetail(ConversationRow):
    # WhatsApp 24h window (step 6.3.2): free-form replies only while open; null for the widget.
    window_open: bool | None = None
    window_expires_at: dt.datetime | None = None
    summary: dict[str, Any] | None
    assigned_user_name: str | None
    lead: LeadBrief | None
    bookings: list[BookingBrief]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    seq: int
    direction: str
    sender: str
    author_user_id: uuid.UUID | None
    author_name: str | None = None
    type: str
    text: str | None
    transcript: str | None
    media_path: str | None
    template_name: str | None
    status: str
    error: str | None = None
    citations: list[dict[str, Any]] | None
    tool_calls: list[dict[str, Any]] | None
    created_at: dt.datetime


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class ReturnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)


class PatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "pending", "closed"] | None = None
    flagged: bool | None = None
    assigned_user_id: uuid.UUID | None = None
    unassign: bool = False


def _visible() -> Any:
    return or_(
        Contact.widget_visitor_id.is_(None), ~Contact.widget_visitor_id.startswith(SANDBOX_PREFIX)
    )


async def _last_messages(session: SessionDep, ids: list[uuid.UUID]) -> dict[uuid.UUID, Message]:
    if not ids:
        return {}
    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id.in_(ids), Message.type != "note")
        .order_by(Message.conversation_id, Message.seq.desc())
        .distinct(Message.conversation_id)
    )
    return {m.conversation_id: m for m in rows}


def _row(conv: Conversation, contact: Contact, last: Message | None) -> ConversationRow:
    return ConversationRow(
        id=conv.id,
        channel=conv.channel,
        module=conv.module,
        mode=conv.mode,
        status=conv.status,
        flagged=conv.flagged,
        assigned_user_id=conv.assigned_user_id,
        contact=ContactOut.model_validate(contact),
        last_message=LastMessage(
            text=last.text or last.transcript,
            sender=last.sender,
            type=last.type,
            created_at=last.created_at,
        )
        if last
        else None,
        awaiting_reply=bool(last and last.direction == "in"),
        last_inbound_at=conv.last_inbound_at,
        updated_at=conv.updated_at,
    )


@router.get("")
async def list_conversations(
    ctx: StaffCtx,
    session: SessionDep,
    channel: Literal["widget", "whatsapp"] | None = None,
    mode: Literal["ai", "human"] | None = None,
    status_: Annotated[Literal["open", "pending", "closed"] | None, Query(alias="status")] = None,
    assigned: Literal["me", "unassigned"] | None = None,
    flagged: bool | None = None,
    awaiting: bool | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ConversationRow]:
    stmt: Select[Conversation, Contact] = (
        select(Conversation, Contact)
        .join(Contact, Contact.id == Conversation.contact_id)
        .where(_visible())
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    if channel:
        stmt = stmt.where(Conversation.channel == channel)
    if mode:
        stmt = stmt.where(Conversation.mode == mode)
    if status_:
        stmt = stmt.where(Conversation.status == status_)
    if assigned == "me":
        stmt = stmt.where(Conversation.assigned_user_id == ctx.user_id)
    elif assigned == "unassigned":
        stmt = stmt.where(Conversation.assigned_user_id.is_(None))
    if flagged is not None:
        stmt = stmt.where(Conversation.flagged.is_(flagged))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Contact.name.ilike(like),
                Contact.phone.ilike(like),
                select(Message.id)
                .where(Message.conversation_id == Conversation.id, Message.text.ilike(like))
                .exists(),
            )
        )
    pairs = (await session.execute(stmt)).all()
    last = await _last_messages(session, [c.id for c, _ in pairs])
    rows = [_row(c, ct, last.get(c.id)) for c, ct in pairs]
    if awaiting is not None:
        rows = [r for r in rows if r.awaiting_reply is awaiting]
    return rows


async def _get(session: SessionDep, conversation_id: uuid.UUID) -> tuple[Conversation, Contact]:
    pair = (
        await session.execute(
            select(Conversation, Contact)
            .join(Contact, Contact.id == Conversation.contact_id)
            .where(Conversation.id == conversation_id)
        )
    ).first()
    if pair is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return pair[0], pair[1]


async def _detail(session: SessionDep, conv: Conversation, contact: Contact) -> ConversationDetail:
    last = (await _last_messages(session, [conv.id])).get(conv.id)
    lead = await session.get(Lead, conv.lead_id) if conv.lead_id else None
    if lead is None:
        lead = await session.scalar(
            select(Lead).where(Lead.contact_id == contact.id).order_by(Lead.created_at.desc())
        )
    bookings = (
        await session.execute(
            select(Booking, Slot)
            .join(Slot, Slot.id == Booking.slot_id)
            .where(Booking.contact_id == contact.id)
            .order_by(Slot.starts_at.desc())
            .limit(5)
        )
    ).all()
    assignee = await session.get(User, conv.assigned_user_id) if conv.assigned_user_id else None
    wa = conv.channel == "whatsapp"
    return ConversationDetail(
        **_row(conv, contact, last).model_dump(),
        window_open=free_form_allowed(conv.last_inbound_at, dt.datetime.now(dt.UTC))
        if wa
        else None,
        window_expires_at=window_expires_at(conv.last_inbound_at) if wa else None,
        summary=conv.summary,
        assigned_user_name=assignee.name if assignee else None,
        lead=LeadBrief.model_validate(lead) if lead else None,
        bookings=[
            BookingBrief(id=b.id, code=b.code, status=b.status, kind=s.kind, starts_at=s.starts_at)
            for b, s in bookings
        ],
    )


@router.get("/events")
async def events(ctx: StaffCtx, request: Request) -> StreamingResponse:
    """`event: changed` `{ids: [...]}` whenever conversations change; `: ping` heartbeats."""
    sm = request.app.state.resources.sessionmaker
    institution_id = ctx.institution_id

    async def stream() -> AsyncIterator[bytes]:
        since = dt.datetime.now(dt.UTC)
        loop = asyncio.get_running_loop()
        end = loop.time() + EVENTS_MAX_S
        yield b"event: ready\ndata: {}\n\n"
        while loop.time() < end:
            if await request.is_disconnected():
                return
            await asyncio.sleep(EVENTS_TICK_S)
            async with tenant_session(sm, institution_id) as session:
                rows = (
                    await session.execute(
                        select(Conversation.id, Conversation.updated_at)
                        .where(Conversation.updated_at > since)
                        .order_by(Conversation.updated_at)
                        .limit(200)
                    )
                ).all()
            if rows:
                since = max(r.updated_at for r in rows)
                payload = json.dumps({"ids": [str(r.id) for r in rows]})
                yield f"event: changed\ndata: {payload}\n\n".encode()
            else:
                yield b": ping\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, _: StaffCtx, session: SessionDep
) -> ConversationDetail:
    conv, contact = await _get(session, conversation_id)
    return await _detail(session, conv, contact)


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: uuid.UUID,
    _: StaffCtx,
    session: SessionDep,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[MessageOut]:
    await _get(session, conversation_id)
    rows = (
        await session.execute(
            select(Message, User.name)
            .outerjoin(User, User.id == Message.author_user_id)
            .where(Message.conversation_id == conversation_id, Message.seq > after)
            .order_by(Message.seq.desc())
            .limit(limit)
        )
    ).all()
    out = []
    for m, name in reversed(rows):
        item = MessageOut.model_validate(m)
        item.author_name = name
        out.append(item)
    return out


async def _staff_name(session: SessionDep, ctx: TenantContext) -> str:
    user = await session.get(User, ctx.user_id)
    return user.name if user else "Staff"


async def _take(session: SessionDep, ctx: TenantContext, conv: Conversation) -> None:
    if conv.mode == "human":
        return
    conv.mode, conv.status = "human", "open"
    conv.assigned_user_id = conv.assigned_user_id or ctx.user_id
    who = await _staff_name(session, ctx)
    await add_message(
        session,
        conv,
        direction="out",
        sender="system",
        type="note",
        status="sent",
        text=f"{who} took over the conversation",
    )


@router.post("/{conversation_id}/takeover")
async def takeover(
    conversation_id: uuid.UUID, ctx: StaffCtx, request: Request, session: SessionDep
) -> ConversationDetail:
    conv, contact = await _get(session, conversation_id)
    before = conv.mode
    await _take(session, ctx, conv)
    await audit_ctx(
        session,
        ctx,
        request,
        action="conversation.takeover",
        entity="conversation",
        entity_id=conv.id,
        before={"mode": before},
        after={"mode": conv.mode},
    )
    return await _detail(session, conv, contact)


@router.post("/{conversation_id}/return-to-ai")
async def return_to_ai(
    conversation_id: uuid.UUID,
    body: ReturnIn,
    ctx: StaffCtx,
    request: Request,
    session: SessionDep,
) -> ConversationDetail:
    conv, contact = await _get(session, conversation_id)
    if conv.mode != "human":
        raise HTTPException(status.HTTP_409_CONFLICT, "Conversation is already with the AI")
    rt = await request.app.state.agent.get()
    await resume_after_handoff(rt.deps, rt.graph, ctx.institution_id, conv.id, body.note)
    conv.mode, conv.status = (
        "ai",
        "open",
    )  # same values resume committed; keeps this session in sync
    who = await _staff_name(session, ctx)
    note = f" — note: {body.note}" if body.note else ""
    await add_message(
        session,
        conv,
        direction="out",
        sender="system",
        type="note",
        status="sent",
        text=f"{who} returned the conversation to the AI{note}",
    )
    await audit_ctx(
        session,
        ctx,
        request,
        action="conversation.return_to_ai",
        entity="conversation",
        entity_id=conv.id,
        before={"mode": "human"},
        after={"mode": "ai", "note": body.note},
    )
    return await _detail(session, conv, contact)


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def staff_send(
    conversation_id: uuid.UUID,
    body: TextIn,
    ctx: StaffCtx,
    request: Request,
    session: SessionDep,
    background: BackgroundTasks,
    redis: RedisDep,
) -> MessageOut:
    """Staff reply. Sending while the AI owns the chat takes it over first (no double replies).
    WhatsApp: only inside the 24h window (6.3.2); delivered by `deliver_message_job`."""
    conv, contact = await _get(session, conversation_id)
    if contact.opted_out_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Contact has opted out")
    if conv.channel == "whatsapp" and not free_form_allowed(
        conv.last_inbound_at, dt.datetime.now(dt.UTC)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The 24-hour WhatsApp window has closed — the parent must write first, or send an "
            "approved template",
        )
    await _take(session, ctx, conv)
    # widget: delivered by the widget's poll → "sent"; WhatsApp: queued for the 6.3 sender
    msg = await add_message(
        session,
        conv,
        direction="out",
        sender="staff",
        text=body.text.strip(),
        author_user_id=ctx.user_id,
        status="sent" if conv.channel == "widget" else "queued",
    )
    if conv.channel == "whatsapp":  # background tasks run after the commit
        background.add_task(enqueue_delivery, redis.enqueue_job, ctx.institution_id, msg.id)
    request.state.audited = True  # message rows are their own record
    out = MessageOut.model_validate(msg)
    out.author_name = await _staff_name(session, ctx)
    return out


@router.post("/{conversation_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_note(
    conversation_id: uuid.UUID, body: TextIn, ctx: StaffCtx, request: Request, session: SessionDep
) -> MessageOut:
    conv, _ = await _get(session, conversation_id)
    msg = await add_message(
        session,
        conv,
        direction="out",
        sender="staff",
        type="note",
        status="sent",
        text=body.text.strip(),
        author_user_id=ctx.user_id,
    )
    request.state.audited = True
    out = MessageOut.model_validate(msg)
    out.author_name = await _staff_name(session, ctx)
    return out


@router.patch("/{conversation_id}")
async def patch_conversation(
    conversation_id: uuid.UUID, body: PatchIn, ctx: StaffCtx, request: Request, session: SessionDep
) -> ConversationDetail:
    """Resolve / reopen, flag, assign (to an active member of this institution) or unassign."""
    conv, contact = await _get(session, conversation_id)
    before = {"status": conv.status, "flagged": conv.flagged, "assigned": conv.assigned_user_id}
    if body.status:
        conv.status = body.status
    if body.flagged is not None:
        conv.flagged = body.flagged
    if body.unassign:
        conv.assigned_user_id = None
    elif body.assigned_user_id:
        member = await session.scalar(
            select(Membership.id).where(
                Membership.user_id == body.assigned_user_id, Membership.status == "active"
            )
        )
        if member is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Not an active member")
        conv.assigned_user_id = body.assigned_user_id
    conv.updated_at = func.now()
    await session.flush()
    await session.refresh(conv)
    await audit_ctx(
        session,
        ctx,
        request,
        action="conversation.update",
        entity="conversation",
        entity_id=conv.id,
        before=before,
        after={"status": conv.status, "flagged": conv.flagged, "assigned": conv.assigned_user_id},
    )
    return await _detail(session, conv, contact)
