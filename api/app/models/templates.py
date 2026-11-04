"""WhatsApp message templates (step 6.5, PLAN §15.2 Templates). One row per name + language.

`body` uses named placeholders `{{name}}`; `variables` fixes their order, which becomes Meta's
positional `{{1}}…{{n}}` on submit and the `body.parameters` order on send."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampsMixin, UUIDPkMixin, enum_check
from app.models.enums import LANGUAGES, TEMPLATE_CATEGORIES, TEMPLATE_STATUSES


class Template(UUIDPkMixin, TenantMixin, TimestampsMixin, Base):
    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("institution_id", "name", "language"),
        enum_check("language", LANGUAGES),
        enum_check("category", TEMPLATE_CATEGORIES),
        enum_check("status", TEMPLATE_STATUSES),
    )

    name: Mapped[str] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(16), server_default="utility")
    body: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), server_default=text("'{}'::varchar[]")
    )
    examples: Mapped[list[str]] = mapped_column(
        ARRAY(String(200)), server_default=text("'{}'::varchar[]")
    )
    status: Mapped[str] = mapped_column(String(16), server_default="draft")
    meta_template_id: Mapped[str | None] = mapped_column(String(64))
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
