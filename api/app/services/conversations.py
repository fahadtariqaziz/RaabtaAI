"""Contacts, conversations and messages (PLAN §13). Session must be tenant-scoped
(`scope_to_tenant` / `tenant_session`): institution_id is stamped by the ORM layer, never passed in.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenancyError
from app.models.conversations import Contact, Conversation, Message

INSTITUTION_KEY = "institution_id"


def _institution(session: AsyncSession) -> uuid.UUID:
    inst = session.info.get(INSTITUTION_KEY)
    if not isinstance(inst, uuid.UUID):
        raise TenancyError("tenant-scoped session required")
    return inst


def thread_id_for(institution_id: uuid.UUID, contact_id: uuid.UUID) -> str:
    """LangGraph thread id (PLAN §4): prefixed by institution so checkpoints never collide."""
    return f"{institution_id}:{contact_id}"


async def get_or_create_contact(
    session: AsyncSession,
    *,
    wa_id: str | None = None,
    widget_visitor_id: str | None = None,
    name: str | None = None,
    phone: str | None = None,
) -> Contact:
    if (wa_id is None) == (widget_visitor_id is None):
        raise ValueError("exactly one of wa_id / widget_visitor_id is required")
    _institution(session)
    where = (
        Contact.wa_id == wa_id
        if wa_id is not None
        else Contact.widget_visitor_id == widget_visitor_id
    )
    contact = await session.scalar(select(Contact).where(where))
    if contact is None:
        contact = Contact(wa_id=wa_id, widget_visitor_id=widget_visitor_id, name=name, phone=phone)
        session.add(contact)
        await session.flush()
    elif name and not contact.name:
        contact.name = name
    return contact


async def open_conversation(
    session: AsyncSession, contact: Contact, *, channel: str, module: str = "admissions"
) -> Conversation:
    """Reuse the contact's open conversation on this channel+module, else start one."""
    inst = _institution(session)
    conv = await session.scalar(
        select(Conversation)
        .where(
            Conversation.contact_id == contact.id,
            Conversation.channel == channel,
            Conversation.module == module,
            Conversation.status != "closed",
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    if conv is None:
        conv = Conversation(
            contact_id=contact.id,
            channel=channel,
            module=module,
            thread_id=thread_id_for(inst, contact.id),
        )
        session.add(conv)
        await session.flush()
    return conv


async def add_message(
    session: AsyncSession,
    conversation: Conversation,
    *,
    direction: str,
    sender: str,
    text: str | None = None,
    type: str = "text",
    **fields: Any,
) -> Message:
    msg = Message(
        conversation_id=conversation.id,
        direction=direction,
        sender=sender,
        type=type,
        text=text,
        status=fields.pop("status", "received" if direction == "in" else "queued"),
        **fields,
    )
    session.add(msg)
    now = datetime.now(UTC)
    if direction == "in":
        conversation.last_inbound_at = now
    conversation.updated_at = now
    await session.flush()
    return msg


async def list_messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    rows = await session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    )
    return list(rows)
