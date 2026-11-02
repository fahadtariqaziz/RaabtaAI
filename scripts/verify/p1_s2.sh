#!/usr/bin/env bash
# Step 1.2 — auth & RBAC (HANDOFF §3).
STEP="p1_s2"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (auth & RBAC)"

check "fresh test DB migrated to head"   reset_test_db
check "auth: login, refresh rotation, lockout, role gating" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_auth.py"
check "members: invite/accept, owner rules, audit rows" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_members.py"
check "lint + types + unit tests"        api_quality

finish
