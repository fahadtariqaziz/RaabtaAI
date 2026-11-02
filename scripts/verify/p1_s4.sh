#!/usr/bin/env bash
# Step 1.4 — conversation domain tables (HANDOFF §3).
STEP="p1_s4"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (conversation domain tables)"

check "fresh test DB migrated to head"      reset_test_db
check "single alembic head + no drift"      bash -c "cd api && [[ \$(uv run alembic heads | wc -l | tr -d ' ') == 1 ]] && uv run alembic -x url=\$IT_MIGRATIONS_URL check"
check "CRUD via services, uniques, indexes, slot capacity, checkpoint tables" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_conversation_models.py"
check "migrations round-trip incl. 0003"    bash -c "cd api && uv run pytest -m integration tests/integration/test_migrations.py"
check "RLS coverage lint covers new tables" bash -c "cd api && uv run pytest -m isolation tests/isolation/test_rls_basics.py"
check "dev DB migrated to head"             make -s migrate
check "lint + types + unit tests"           api_quality

finish
