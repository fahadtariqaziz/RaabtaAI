#!/usr/bin/env bash
# Step 3.6 (HANDOFF §3).
STEP="p3_s6"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (context assembly & compaction)"

check "context: cache order, determinism, budgets, no timestamps cached, append-only prefix" \
  bash -c "cd api && uv run pytest tests/unit/test_context.py"
check "lint + types + unit tests"        api_quality

finish
