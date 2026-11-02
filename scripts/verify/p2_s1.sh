#!/usr/bin/env bash
# Step 2.1 (HANDOFF §3).
STEP="p2_s1"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (document upload & storage)"

check "fresh test DB migrated to head"   reset_test_db
check "kb documents: upload seed files, reject exe/oversize/dup, version bump, delete" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_kb_documents.py"
check "migration 0004 round-trip + no drift" bash -c "cd api && uv run alembic -x url=\$IT_MIGRATIONS_URL downgrade 0003 && uv run alembic -x url=\$IT_MIGRATIONS_URL upgrade head && uv run alembic -x url=\$IT_MIGRATIONS_URL check"
check "lint + types + unit tests"        api_quality

finish
