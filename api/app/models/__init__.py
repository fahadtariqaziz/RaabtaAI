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
from app.models.facts import FeeItem, KeyDate, Program, Scholarship, TransportRoute
from app.models.kb import Chunk, Document

__all__ = [
    "AuditLog",
    "Booking",
    "Chunk",
    "Contact",
    "Conversation",
    "Document",
    "FeeItem",
    "Followup",
    "Institution",
    "KeyDate",
    "Lead",
    "LlmRun",
    "Membership",
    "Message",
    "Plan",
    "Program",
    "Scholarship",
    "Slot",
    "TransportRoute",
    "UsageDaily",
    "User",
    "WebhookEvent",
]
