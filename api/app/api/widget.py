"""Public widget API (PLAN §14 Widget, §15.1; step 4.1). No admin auth: the widget gets a
24h session JWT bound to (institution, visitor, contact, origin) from `POST /widget/sessions`.

Check-then-send (D-11): the SSE stream emits `status` events while tools run; the reply text is
emitted (`message`) only after the whole graph — including `answer_check` — finished, so an
unchecked draft never reaches the browser."""

import asyncio
import datetime as dt
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.inbound import InboundEvent, TurnResult, run_inbound
from app.agent.phrases import phrase
from app.agent.runtime import AgentRuntimeHolder
from app.agent.tools.leads import normalize_pk_phone, upsert_lead
from app.api.deps import RedisDep, SessionDep, SettingsDep, client_ip, require_role
from app.core.tenancy import TenantContext, admin_session, tenant_session
from app.models.conversations import Contact
from app.models.core import Institution
from app.services import widget as w
from app.services.conversations import get_or_create_contact, open_conversation

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/widget", tags=["widget"])
institution_router = APIRouter(prefix="/institution", tags=["institution"])
LIVE = ("trial", "active")


def _too_many(detail: str = "Too many requests") -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail)


async def _institution_by_slug(request: Request, slug: str) -> Institution:
    async with admin_session(request.app.state.resources.sessionmaker) as session:
        inst = await session.scalar(select(Institution).where(Institution.slug == slug))
        if inst is None or inst.status not in LIVE:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown institution")
        session.expunge(inst)
        return inst


async def _institution(request: Request, institution_id: uuid.UUID) -> Institution:
    async with tenant_session(request.app.state.resources.sessionmaker, institution_id) as session:
        inst = await session.get(Institution, institution_id)
        if inst is None or inst.status not in LIVE:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown institution")
        session.expunge(inst)
        return inst


async def widget_session(
    session_id: uuid.UUID,
    request: Request,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
    origin: Annotated[str | None, Header()] = None,
) -> w.WidgetSession:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing session token")
    try:
        sess = w.decode_session_token(authorization[7:].strip(), session_id, settings)
    except w.WidgetAuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session token") from None
    if origin and sess.origin and origin.rstrip("/") != sess.origin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin mismatch")
    return sess


SessionTokenDep = Annotated[w.WidgetSession, Depends(widget_session)]


@router.get("/config/{slug}")
async def get_config(slug: str, request: Request) -> dict[str, Any]:
    return w.public_config(await _institution_by_slug(request, slug))


class SessionIn(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    visitor_id: str | None = Field(default=None, max_length=64)


class SessionOut(BaseModel):
    session_id: uuid.UUID
    token: str
    visitor_id: str
    expires_at: dt.datetime


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionIn,
    request: Request,
    settings: SettingsDep,
    redis: RedisDep,
    origin: Annotated[str | None, Header()] = None,
) -> SessionOut:
    now = dt.datetime.now(dt.UTC)
    limit, window = w.SESSION_RATE_PER_IP
    if not await w.hit(redis, f"wsess:ip:{client_ip(request)}", limit, window, now):
        raise _too_many()
    inst = await _institution_by_slug(request, body.slug)
    if not w.origin_allowed(origin, inst, settings):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed for this institution")
    visitor = (
        body.visitor_id
        if body.visitor_id and w.VISITOR_RE.match(body.visitor_id)
        else w.new_visitor_id()
    )
    async with tenant_session(request.app.state.resources.sessionmaker, inst.id) as session:
        contact = await get_or_create_contact(session, widget_visitor_id=visitor)
        contact_id = contact.id
    sess = w.WidgetSession(
        session_id=uuid.uuid4(),
        institution_id=inst.id,
        contact_id=contact_id,
        visitor_id=visitor,
        origin=str(origin).rstrip("/"),
    )
    token, exp = w.issue_session_token(sess, settings, now)
    return SessionOut(session_id=sess.session_id, token=token, visitor_id=visitor, expires_at=exp)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=w.MAX_MESSAGE_CHARS)
    client_msg_id: str | None = Field(default=None, max_length=64)
    lang: str | None = Field(default=None, max_length=16, description="UI language hint")


async def _turn_stream(
    request: Request, sess: w.WidgetSession, body: MessageIn
) -> AsyncIterator[bytes]:
    lang = w.ui_lang(body.lang)
    yield w.sse("status", {"text": w.status_text("_thinking", lang)})
    holder: AgentRuntimeHolder = request.app.state.agent
    try:
        rt = await holder.get()
    except Exception as exc:  # misconfiguration (e.g. no API key) — fail visibly, no stack
        log.error("widget.agent_unavailable", error=type(exc).__name__)
        yield w.sse("error", {"text": phrase("error", lang)})
        yield w.sse("done", {"status": "error"})
        return
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    hook_key = f"{sess.institution_id}:{sess.contact_id}"

    async def on_tool_start(tool: str) -> None:
        await queue.put(("status", {"text": w.status_text(tool, lang), "tool": tool}))

    async def run() -> TurnResult:
        rt.deps.status_hooks[hook_key] = on_tool_start
        try:
            return await run_inbound(
                rt.deps,
                rt.graph,
                InboundEvent(
                    institution_id=sess.institution_id,
                    channel="widget",
                    text=body.text.strip(),
                    widget_visitor_id=sess.visitor_id,
                    client_msg_id=body.client_msg_id,
                ),
            )
        finally:
            if rt.deps.status_hooks.get(hook_key) is on_tool_start:
                rt.deps.status_hooks.pop(hook_key, None)

    # The turn runs to completion (persisted) even if the visitor closes the tab mid-stream.
    task = asyncio.create_task(run())
    tasks: set[asyncio.Task[Any]] = request.app.state.widget_tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    while not task.done():
        getter = asyncio.ensure_future(queue.get())
        finished, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
        if getter in finished:
            event, data = getter.result()
            yield w.sse(event, data)
        else:
            getter.cancel()
    while not queue.empty():
        event, data = queue.get_nowait()
        yield w.sse(event, data)
    try:
        result = task.result()
    except Exception as exc:
        log.error("widget.turn_failed", error=type(exc).__name__)
        yield w.sse("error", {"text": phrase("error", lang)})
        yield w.sse("done", {"status": "error"})
        return
    if result.reply_kind == "blocked":
        await w.strike(request.app.state.resources.redis, sess.session_id)
    for event, data in w.turn_events(result):
        yield w.sse(event, data)
    human = result.status in ("human_mode", "escalated") or result.reply_kind == "handoff"
    yield w.sse("done", {"status": result.status, "human": human})


@router.post("/sessions/{session_id}/messages")
async def post_message(
    body: MessageIn, request: Request, sess: SessionTokenDep, redis: RedisDep
) -> StreamingResponse:
    now = dt.datetime.now(dt.UTC)
    if await w.locked_out(redis, sess.session_id):
        raise _too_many("Session locked")
    ip_limit, ip_window = w.MSG_RATE_PER_IP
    s_limit, s_window = w.MSG_RATE_PER_SESSION
    if not await w.hit(redis, f"wmsg:ip:{client_ip(request)}", ip_limit, ip_window, now):
        raise _too_many()
    if not await w.hit(redis, f"wmsg:s:{sess.session_id}", s_limit, s_window, now):
        raise _too_many()
    return StreamingResponse(
        _turn_stream(request, sess, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=7, max_length=32)
    student_name: str | None = Field(default=None, max_length=120)
    interest: str | None = Field(default=None, max_length=200)


@router.post("/sessions/{session_id}/lead")
async def post_lead(
    body: LeadIn, request: Request, sess: SessionTokenDep, redis: RedisDep
) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC)
    s_limit, s_window = w.MSG_RATE_PER_SESSION
    if not await w.hit(redis, f"wmsg:s:{sess.session_id}", s_limit, s_window, now):
        raise _too_many()
    phone = normalize_pk_phone(body.phone)
    if phone is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid Pakistani phone number")
    sm = request.app.state.resources.sessionmaker
    async with tenant_session(sm, sess.institution_id) as session:
        contact = await session.get(Contact, sess.contact_id)
        if contact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session contact not found")
        contact.name = contact.name or body.name.strip()
        contact.phone = contact.phone or phone
        conv = await open_conversation(session, contact, channel="widget")
        lead = await upsert_lead(
            session,
            contact_id=contact.id,
            conversation_id=conv.id,
            channel="widget",
            phone=phone,
            guardian_name=body.name.strip(),
            student_name=body.student_name,
            interest=body.interest,
        )
        return {"ok": True, "lead_id": str(lead.id)}


@router.get("/sessions/{session_id}/whatsapp-link")
async def get_whatsapp_link(
    request: Request, sess: SessionTokenDep, redis: RedisDep, lang: str | None = None
) -> dict[str, str]:
    inst = await _institution(request, sess.institution_id)
    number = w.widget_settings(inst).get("whatsapp_number")
    if not number:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "WhatsApp not configured")
    return {"url": await w.whatsapp_link(redis, sess, str(number), w.ui_lang(lang))}


@router.get("/sessions/{session_id}/updates")
async def get_updates(
    request: Request, sess: SessionTokenDep, after: Annotated[int, Query(ge=0)] = 0
) -> dict[str, Any]:
    """Polled by the widget while staff own the chat (I-18): outbound staff/system texts with
    `seq > after` for this visitor's widget conversation + the current mode."""
    sm = request.app.state.resources.sessionmaker
    async with tenant_session(sm, sess.institution_id) as session:
        return await w.staff_updates(session, sess.contact_id, after)


@institution_router.get("/widget-snippet")
async def widget_snippet(
    ctx: Annotated[TenantContext, Depends(require_role("staff"))],
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    inst = await session.get(Institution, ctx.institution_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Institution not found")
    return {
        "snippet": w.snippet(inst.slug, settings),
        "allowed_origins": list(w.widget_settings(inst).get("allowed_origins", [])),
    }
