#!/usr/bin/env bash
# Step 2.7 (HANDOFF §3).
STEP="p2_s7"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (citations & playground)"

check "fresh test DB migrated to head"   reset_test_db
check "citation schema + quotes + packing" \
  bash -c "cd api && uv run pytest tests/unit/test_citations.py"
check "playground endpoint: cited chunks + approved facts" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_playground.py"
check "lint + types + unit tests"        api_quality

finish
