#!/usr/bin/env bash
# Step 3.2 (HANDOFF §3).
STEP="p3_s2"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (prompt files & loader)"

check "prompts: front-matter, no dates in cached prompts, tenant block deterministic, phrases" \
  bash -c "cd api && uv run pytest tests/unit/test_prompts.py"
check "lint + types + unit tests"        api_quality

finish
