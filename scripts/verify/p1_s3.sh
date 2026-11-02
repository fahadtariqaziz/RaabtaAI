#!/usr/bin/env bash
# Step 1.3 — tenant context & Row-Level Security (HANDOFF §3).
STEP="p1_s3"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (tenant context & RLS)"

check "fresh test DB migrated to head"    reset_test_db
check "roles app_tenant/app_admin exist; raabta_app may SET ROLE to both" \
  bash -c "docker compose exec -T postgres psql -U raabta -d raabta_test -tAc \"select count(*) from pg_auth_members m join pg_roles r on r.oid=m.roleid join pg_roles u on u.oid=m.member where u.rolname='raabta_app' and r.rolname in ('app_tenant','app_admin')\" | grep -qx 2"
check "RLS: zero rows w/o context, cross-tenant writes rejected, ORM layer, coverage lint" \
  bash -c "cd api && uv run pytest -m isolation tests/isolation/test_rls_basics.py"
check "auth still green under RLS"        bash -c "cd api && uv run pytest -m integration tests/integration/test_auth.py tests/integration/test_members.py"
check "lint + types + unit tests"         api_quality

finish
