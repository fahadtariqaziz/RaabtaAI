"""Core tenant tables (PLAN §13): plans, institutions, users, memberships, audit_log,
usage_daily, webhook_events."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
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
    INSTITUTION_STATUSES,
    INSTITUTION_TYPES,
    MEMBERSHIP_ROLES,
    MEMBERSHIP_STATUSES,
    WEBHOOK_STATUSES,
)


class Plan(UUIDPkMixin, CreatedAtMixin, Base):
    """Subscription plan limits (global, not tenant-scoped). Pricing decided later (D-05)."""

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    price_pkr: Mapped[int | None] = mapped_column(Integer)
    monthly_conversations: Mapped[int] = mapped_column(Integer)
    monthly_template_sends: Mapped[int] = mapped_column(Integer)
    monthly_ai_budget_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    seats: Mapped[int] = mapped_column(Integer)


class Institution(UUIDPkMixin, TimestampsMixin, Base):
    """A client (school/college/university). The tenant root — not itself RLS-scoped by FK."""

    __tablename__ = "institutions"
    __table_args__ = (
        enum_check("type", INSTITUTION_TYPES),
        enum_check("status", INSTITUTION_STATUSES),
    )

    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(16))
    city: Mapped[str] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Karachi")
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), server_default=text("ARRAY['en','ur','roman_ur']::varchar[]")
    )
    quiet_hours: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("""'{"start": "21:00", "end": "09:00"}'::jsonb""")
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), server_default="trial")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    wa_phone_number_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    waba_id: Mapped[str | None] = mapped_column(String(64))
    facts_version: Mapped[int] = mapped_column(Integer, server_default="0")


class User(UUIDPkMixin, TimestampsMixin, Base):
    """A person who logs into the admin panel. Email is stored lower-cased (unique)."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # null until invite accepted
    name: Mapped[str] = mapped_column(String(120))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    locale: Mapped[str] = mapped_column(String(8), server_default="en")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(UUIDPkMixin, TenantMixin, CreatedAtMixin, Base):
    """User ↔ institution with a role. A user can belong to several institutions."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("institution_id", "user_id"),
        enum_check("role", MEMBERSHIP_ROLES),
        enum_check("status", MEMBERSHIP_STATUSES),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="invited")
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Pending invitation: SHA-256 of the one-time token (raw token is shown once to the inviter).
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDPkMixin, CreatedAtMixin, Base):
    """Who changed what (PLAN §10 G15). institution_id is null only for platform-level actions."""

    __tablename__ = "audit_log"
    __table_args__ = (Index(None, "institution_id", "created_at"),)

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(45))


class UsageDaily(Base):
    """Per-institution daily counters (rolled up nightly, step 1.6)."""

    __tablename__ = "usage_daily"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    conversations: Mapped[int] = mapped_column(Integer, server_default="0")
    messages_in: Mapped[int] = mapped_column(Integer, server_default="0")
    messages_out: Mapped[int] = mapped_column(Integer, server_default="0")
    template_sends: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_in: Mapped[int] = mapped_column(BigInteger, server_default="0")
    tokens_out: Mapped[int] = mapped_column(BigInteger, server_default="0")
    llm_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    leads: Mapped[int] = mapped_column(Integer, server_default="0")
    bookings: Mapped[int] = mapped_column(Integer, server_default="0")
    fee_recovered_pkr: Mapped[int] = mapped_column(BigInteger, server_default="0")


class WebhookEvent(UUIDPkMixin, Base):
    """Raw inbound webhook for idempotency + replay (unique per provider event id)."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id"),
        enum_check("status", WEBHOOK_STATUSES),
    )

    provider: Mapped[str] = mapped_column(String(32))
    event_id: Mapped[str] = mapped_column(String(128))
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="SET NULL")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default="received")
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
