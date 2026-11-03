#!/usr/bin/env bash
# Step 3.8 (HANDOFF §3).
STEP="p3_s8"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (summarizer & contact memory)"

check "summarizer: goal tracking, input format, LTM writes, no invented phones" \
  bash -c "cd api && uv run pytest tests/unit/test_summarizer.py"
check "lint + types + unit tests"        api_quality

finish
