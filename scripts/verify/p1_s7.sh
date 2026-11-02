#!/usr/bin/env bash
# Step 1.7 — tenant isolation test suite (HANDOFF §3).
STEP="p1_s7"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (tenant isolation suite)"

check "fresh test DB migrated to head"   reset_test_db
check "every /api/v1 route classified (public or tenant-tested)" \
  bash -c "cd api && uv run pytest -m isolation tests/isolation/test_endpoints.py::test_every_route_is_classified"
check "isolation suite: RLS basics + cross-tenant attempts on every route" \
  bash -c "cd api && uv run pytest -m isolation tests/isolation"
check "lint + types + unit tests"        api_quality

finish
