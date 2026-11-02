"""SQL for Row-Level Security, used by migrations (PLAN §18).

Keep these helpers stable: migrations call them, so changing output changes history. If a policy
shape must change, write new helpers and a new migration.
"""

POLICY = "tenant_isolation"

# Tables that are global on purpose (no institution_id, or platform-level rows). Everything else
# with an `institution_id` must have RLS — enforced by tests/integration/test_rls_coverage.py.
GLOBAL_TABLES = frozenset(
    {
        "alembic_version",
        "plans",
        "users",  # identity is global; tenant code reaches users only via memberships
        "webhook_events",  # provider-level; tenant resolved later by phone_number_id
        "checkpoints",  # LangGraph (thread_id prefixed by institution_id)
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    }
)

CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION app_current_institution() RETURNS uuid
LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.institution_id', true), '')::uuid $$
"""

DROP_FUNCTION = "DROP FUNCTION IF EXISTS app_current_institution()"


def enable_rls(table: str, column: str = "institution_id") -> list[str]:
    """ENABLE + FORCE RLS and one policy for all commands (read and write check)."""
    cond = f"{column} = app_current_institution()"
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {POLICY} ON {table} USING ({cond}) WITH CHECK ({cond})",
    ]


def disable_rls(table: str) -> list[str]:
    return [
        f"DROP POLICY IF EXISTS {POLICY} ON {table}",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
    ]
