"""Allowed values for VARCHAR+CHECK enum columns. Single source for models, schemas and tests."""

INSTITUTION_TYPES = ("school", "college", "university")
INSTITUTION_STATUSES = ("trial", "active", "suspended")
LANGUAGES = ("en", "ur", "roman_ur")
MEMBERSHIP_ROLES = ("owner", "admin", "staff")
MEMBERSHIP_STATUSES = ("invited", "active", "disabled")
WEBHOOK_STATUSES = ("received", "processed", "failed", "ignored")
CHANNELS = ("whatsapp", "widget")
MODULES = ("admissions", "fees")
CONVERSATION_MODES = ("ai", "human")
CONVERSATION_STATUSES = ("open", "pending", "closed")
MESSAGE_DIRECTIONS = ("in", "out")
MESSAGE_SENDERS = ("contact", "ai", "staff", "system")
MESSAGE_TYPES = ("text", "audio", "image", "document", "template", "interactive", "note")
MESSAGE_STATUSES = ("received", "queued", "sent", "delivered", "read", "failed")
LEAD_SOURCES = ("widget", "whatsapp", "manual", "import")
LEAD_STATUSES = ("new", "contacted", "visit_booked", "applied", "admitted", "lost")
SLOT_KINDS = ("visit", "test", "counselling")
BOOKING_STATUSES = ("booked", "confirmed", "cancelled", "attended", "no_show")
FOLLOWUP_STATUSES = ("pending", "sent", "cancelled", "failed")
DOCUMENT_KINDS = ("pdf", "docx", "xlsx", "csv")
# Pipeline order (PLAN §5 STEER): uploaded → parsing → chunking → embedding → extracting → ready.
DOCUMENT_STATUSES = (
    "uploaded",
    "parsing",
    "chunking",
    "embedding",
    "extracting",
    "ready",
    "failed",
    "superseded",
)
CHUNK_LANGS = ("en", "ur", "roman_ur", "mixed")
FACT_STATUSES = ("pending", "approved", "rejected", "superseded")
FACT_ORIGINS = ("table", "llm", "seed", "manual")
FEE_FREQUENCIES = ("one_time", "monthly", "quarterly", "annual", "per_semester")
