"""Import every model module here so `Base.metadata` is complete (Alembic autogenerate/check)."""

from app.models.core import (
    AuditLog,
    Institution,
    Membership,
    Plan,
    UsageDaily,
    User,
    WebhookEvent,
)

__all__ = ["AuditLog", "Institution", "Membership", "Plan", "UsageDaily", "User", "WebhookEvent"]
