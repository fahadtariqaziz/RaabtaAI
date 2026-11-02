"""invitations, db roles and row-level security on tenant tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02

Roles (cluster-wide, created if missing, never dropped on downgrade):
- app_tenant: NOBYPASSRLS — per-request role for tenant routes.
- app_admin:  BYPASSRLS   — explicit platform role (auth lookups, superadmin, seeds, jobs).
The runtime login role `raabta_app` (infra/db/init.sql) may SET ROLE to both. Creating a BYPASSRLS
role needs a superuser (or a role with BYPASSRLS) to run this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.rls import CREATE_FUNCTION, DROP_FUNCTION, disable_rls, enable_rls

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("memberships", "audit_log", "usage_daily")

ROLES_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_tenant') THEN
    CREATE ROLE app_tenant NOLOGIN NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_admin') THEN
    CREATE ROLE app_admin NOLOGIN BYPASSRLS;
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'raabta_app') THEN
    GRANT app_tenant TO raabta_app;
    GRANT app_admin TO raabta_app WITH INHERIT FALSE;
  END IF;
END $$
"""

GRANTS_SQL = [
    "GRANT USAGE ON SCHEMA public TO app_tenant, app_admin",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_tenant, app_admin",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_tenant, app_admin",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_tenant, app_admin",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_tenant, app_admin",
    # Global tables a tenant must never write.
    "REVOKE INSERT, UPDATE, DELETE ON plans, webhook_events, alembic_version FROM app_tenant",
]


def upgrade() -> None:
    op.add_column(
        "memberships", sa.Column("invite_token_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "memberships",
        sa.Column("invite_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_memberships_invite_token_hash"), "memberships", ["invite_token_hash"]
    )

    op.execute(ROLES_SQL)
    for stmt in GRANTS_SQL:
        op.execute(stmt)
    op.execute(CREATE_FUNCTION)
    for stmt in enable_rls("institutions", column="id"):
        op.execute(stmt)
    for table in TENANT_TABLES:
        for stmt in enable_rls(table):
            op.execute(stmt)


def downgrade() -> None:
    for table in (*TENANT_TABLES, "institutions"):
        for stmt in disable_rls(table):
            op.execute(stmt)
    op.execute(DROP_FUNCTION)
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_tenant, app_admin"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM app_tenant, app_admin"
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_tenant, app_admin")
    op.drop_constraint(op.f("uq_memberships_invite_token_hash"), "memberships", type_="unique")
    op.drop_column("memberships", "invite_expires_at")
    op.drop_column("memberships", "invite_token_hash")
