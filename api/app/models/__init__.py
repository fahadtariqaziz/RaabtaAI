"""Import every model module here so `Base.metadata` is complete (Alembic autogenerate/check)."""

from app.models.conversations import (
    Booking,
    Contact,
    Conversation,
    Followup,
    Lead,
    LlmRun,
    Message,
    Slot,
)
from app.models.core import (
    AuditLog,
    Institution,
    Membership,
    Plan,
    UsageDaily,
    User,
    WebhookEvent,
)

__all__ = [
    "AuditLog",
    "Booking",
    "Contact",
    "Conversation",
    "Followup",
    "Institution",
    "Lead",
    "LlmRun",
    "Membership",
    "Message",
    "Plan",
    "Slot",
    "UsageDaily",
    "User",
    "WebhookEvent",
]
