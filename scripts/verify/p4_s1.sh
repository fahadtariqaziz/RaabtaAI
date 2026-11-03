#!/usr/bin/env bash
# Step 4.1 (HANDOFF §3): public widget API — config, sessions (origin allowlist, JWT), SSE
# check-then-send, lead, WhatsApp link, rate/auth limits. Zero spend (FakeLLM / AGENT_LLM=demo).
STEP="p4_s1"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (public chat API, SSE)"
trap stop_demo_api EXIT

check "fresh test DB migrated to head"   reset_test_db
check "seed + ingest demo institutions into the test DB" seed_and_ingest_test_db
check "D-11: failed-check draft never streamed; approved reply after tool status" \
  bash -c "cd '$ROOT/api' && uv run pytest -m integration tests/integration/test_widget_api.py"
check "widget bundle built (served by the API)" pnpm -C widget build
check "demo API up on :$DEMO_API_PORT"  start_demo_api
check "smoke: config/session/SSE/slots/lead/wa-link/auth/origin/size caps" \
  bash -c "cd '$ROOT/api' && uv run python -m scripts.widget_smoke --base '$DEMO_API' --origin '$DEMO_API'"
stop_demo_api
check "lint + types + unit tests"        api_quality

finish
