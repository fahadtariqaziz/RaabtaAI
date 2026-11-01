"""Allowed values for VARCHAR+CHECK enum columns. Single source for models, schemas and tests."""

INSTITUTION_TYPES = ("school", "college", "university")
INSTITUTION_STATUSES = ("trial", "active", "suspended")
LANGUAGES = ("en", "ur", "roman_ur")
MEMBERSHIP_ROLES = ("owner", "admin", "staff")
MEMBERSHIP_STATUSES = ("invited", "active", "disabled")
WEBHOOK_STATUSES = ("received", "processed", "failed", "ignored")
