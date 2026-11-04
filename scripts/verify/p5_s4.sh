#!/usr/bin/env bash
# Steps 5.2–5.10 API (HANDOFF §3): tenant isolation over every route (incl. the new inbox/leads/
# slots/metrics/settings routes), the takeover invariant (FakeLLM), superadmin paths, then a live
# smoke of every admin endpoint against the zero-spend demo API (AGENT_LLM=demo).
STEP="p5_s4"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (admin API: inbox, leads, slots, metrics, settings, superadmin)"
trap stop_demo_api EXIT

check "fresh test DB migrated to head"   reset_test_db
check "seed + ingest demo institutions into the test DB" seed_and_ingest_test_db
check "takeover → staff reply → widget poll → return to AI (FakeLLM)" \
  bash -c "cd '$ROOT/api' && uv run pytest -m integration tests/integration/test_inbox.py -q"
check "isolation: every route + superadmin impersonation" \
  bash -c "cd '$ROOT/api' && uv run pytest -m isolation tests/isolation -q"
check "widget bundle built (staff-reply polling)" pnpm -C widget build
flush_test_redis
check "demo API up on :$DEMO_API_PORT"  start_demo_api
check "smoke: all admin endpoints on the demo API" \
  bash -c "cd '$ROOT/api' && uv run python -m scripts.admin_smoke --base '$DEMO_API'"
stop_demo_api
check "lint + types + unit tests"        api_quality

finish
