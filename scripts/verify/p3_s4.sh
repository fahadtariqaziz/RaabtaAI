#!/usr/bin/env bash
# Step 3.4 (HANDOFF §3).
STEP="p3_s4"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (tool registry & admissions tools)"

check "fresh test DB migrated to head"   reset_test_db
check "registry: strict schemas (snapshot), permission gates, error wrapping, manifest" \
  bash -c "cd api && uv run pytest tests/unit/test_registry.py"
check "admissions tools: approved facts + citations, tenant scoping, leads, booking, follow-ups" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_tools_admissions.py"
check "GET /internal/tools classified in the isolation suite" \
  bash -c "cd api && uv run pytest -m integration tests/isolation/test_endpoints.py -k 'classified or tools'"
check "lint + types + unit tests"        api_quality

finish
