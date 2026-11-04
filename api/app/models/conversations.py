"""Conversation domain (PLAN §13): contacts, conversations, messages, llm_runs, leads, slots,
bookings, followups. All tenant-scoped (TenantMixin + RLS in migration 0003)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedAtMixin,
    TenantMixin,
    TimestampsMixin,
    UUIDPkMixin,
    enum_check,
)
from app.models.enums import (
    BOOKING_STATUSES,
    CHANNELS,
    CONVERSATION_MODES,
    CONVERSATION_STATUSES,
    FOLLOWUP_STATUSES,
    LANGUAGES,
    LEAD_SOURCES,
    LEAD_STATUSES,
    MESSAGE_DIRECTIONS,
    MESSAGE_SENDERS,
    MESSAGE_STATUSES,
    MESSAGE_TYPES,
    MODULES,
    SLOT_KINDS,
)


def _fk(table: str, ondelete: str = "CASCADE") -> ForeignKey:
    return ForeignKey(f"{table}.id", ondelete=ondelete)


def _uuid() -> UUID[uuid.UUID]:
    return UUID(as_uuid=True)


class Contact(UUIDPkMixin, TenantMixin, CreatedAtMixin, Base):
    """A parent/student reaching the institution (WhatsApp number and/or widget visitor)."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("institution_id", "wa_id"),
        UniqueConstraint("institution_id", "widget_visitor_id"),
        enum_check("preferred_language", LANGUAGES),
        Index(None, "institution_id", "created_at"),
    )

    wa_id: Mapped[str | None] = mapped_column(String(32))
    widget_visitor_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    preferred_language: Mapped[str | None] = mapped_column(String(16))
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Fee module (step 7.2): {"student_refs": [...], "until": iso-datetime}
    verified: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Lead(UUIDPkMixin, TenantMixin, TimestampsMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        enum_check("source", LEAD_SOURCES),
        enum_check("status", LEAD_STATUSES),
        Index(None, "institution_id", "created_at"),
        Index(None, "institution_id", "status"),
    )

    contact_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("contacts", "SET NULL"))
    student_name: Mapped[str | None] = mapped_column(String(120))
    guardian_name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    interest: Mapped[str | None] = mapped_column(String(200))  # class / program asked about
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="new")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("users", "SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(UUIDPkMixin, TenantMixin, TimestampsMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        enum_check("channel", CHANNELS),
        enum_check("module", MODULES),
        enum_check("mode", CONVERSATION_MODES),
        enum_check("status", CONVERSATION_STATUSES),
        Index(None, "institution_id", "created_at"),
        Index(None, "institution_id", "status", "updated_at"),
    )

    contact_id: Mapped[uuid.UUID] = mapped_column(_uuid(), _fk("contacts"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    module: Mapped[str] = mapped_column(String(16), server_default="admissions")
    mode: Mapped[str] = mapped_column(String(8), server_default="ai")
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("users", "SET NULL"))
    status: Mapped[str] = mapped_column(String(16), server_default="open")
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # LangGraph thread: f"{institution_id}:{contact_id}" (PLAN §4) — shared across a contact's
    # conversations on purpose, hence not unique.
    thread_id: Mapped[str] = mapped_column(String(80), index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("leads", "SET NULL"))
    flagged: Mapped[bool] = mapped_column(Boolean, server_default="false")


class LlmRun(UUIDPkMixin, TenantMixin, CreatedAtMixin, Base):
    """One Claude call: tokens + cost per institution (CLAUDE.md, PLAN §19)."""

    __tablename__ = "llm_runs"
    __table_args__ = (Index(None, "institution_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        _uuid(), _fk("conversations", "SET NULL"), index=True
    )
    node: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    skills: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), server_default=text("'{}'::varchar[]")
    )
    effort: Mapped[str | None] = mapped_column(String(8))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    fallback_used: Mapped[bool] = mapped_column(Boolean, server_default="false")
    error: Mapped[str | None] = mapped_column(Text)


class Message(UUIDPkMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        enum_check("direction", MESSAGE_DIRECTIONS),
        enum_check("sender", MESSAGE_SENDERS),
        enum_check("type", MESSAGE_TYPES),
        enum_check("status", MESSAGE_STATUSES),
        UniqueConstraint("wa_message_id"),
        UniqueConstraint("conversation_id", "client_msg_id"),
        Index(None, "institution_id", "created_at"),
        Index(None, "conversation_id", "seq"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(_uuid(), _fk("conversations"))
    # Insert order (timestamps tie within a transaction); use for transcript ordering.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    direction: Mapped[str] = mapped_column(String(4))
    sender: Mapped[str] = mapped_column(String(8))
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("users", "SET NULL"))
    type: Mapped[str] = mapped_column(String(16), server_default="text")
    text: Mapped[str | None] = mapped_column(Text)
    media_path: Mapped[str | None] = mapped_column(String(512))
    transcript: Mapped[str | None] = mapped_column(Text)
    template_name: Mapped[str | None] = mapped_column(String(128))
    wa_message_id: Mapped[str | None] = mapped_column(String(128))
    client_msg_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="received")
    # Delivery failure reason (WhatsApp sender, step 6.3) — shown in the inbox, never PII.
    error: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    llm_run_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("llm_runs", "SET NULL"))


class Slot(UUIDPkMixin, TenantMixin, CreatedAtMixin, Base):
    """Bookable time window (campus visit, entry test, counselling)."""

    __tablename__ = "slots"
    __table_args__ = (
        enum_check("kind", SLOT_KINDS),
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        CheckConstraint("capacity > 0", name="capacity_positive"),
        CheckConstraint("booked_count >= 0 AND booked_count <= capacity", name="within_capacity"),
        Index(None, "institution_id", "starts_at"),
    )

    kind: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int] = mapped_column(Integer)
    booked_count: Mapped[int] = mapped_column(Integer, server_default="0")
    location: Mapped[str | None] = mapped_column(String(200))


class Booking(UUIDPkMixin, TenantMixin, TimestampsMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        enum_check("status", BOOKING_STATUSES),
        UniqueConstraint("institution_id", "code"),
        Index(None, "institution_id", "created_at"),
    )

    slot_id: Mapped[uuid.UUID] = mapped_column(_uuid(), _fk("slots"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("contacts", "SET NULL"))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("leads", "SET NULL"))
    student_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), server_default="booked")
    code: Mapped[str] = mapped_column(String(12))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Followup(UUIDPkMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "followups"
    __table_args__ = (
        enum_check("status", FOLLOWUP_STATUSES),
        Index(None, "institution_id", "created_at"),
        Index(None, "status", "due_at"),  # scheduler scan (platform job, admin role)
    )

    contact_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("contacts"))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(_uuid(), _fk("leads"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(32))
    template_name: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Kind-specific data, e.g. {"booking_id": ...} for visit reminders (step 6.7).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
