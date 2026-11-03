#!/usr/bin/env bash
# Step 3.5 (HANDOFF §3). Graph tests use a scripted LLM (no spend) on the RLS test DB.
STEP="p3_s5"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (LangGraph inbound graph)"

check "fresh test DB migrated to head"   reset_test_db
check "graph edges: blocked, off-topic, simple, complex, repair, fallback, refusal, loop cap" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_graph.py -k 'not handoff and not opt_out'"
check "handoff interrupt → human mode gate → resume with staff note (Postgres checkpointer)" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_graph.py -k handoff"
check "pre-graph gates: opt-out, dedupe, per-contact rate limit (Redis)" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_graph.py -k opt_out"
check "lint + types + unit tests"        api_quality

finish
