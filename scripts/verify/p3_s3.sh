#!/usr/bin/env bash
# Step 3.3 (HANDOFF §3).
STEP="p3_s3"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (skills loader & packs)"

check "skills: 9 packs ≤ 1.2k tokens, selection matrix, cap, deterministic order" \
  bash -c "cd api && uv run pytest tests/unit/test_skills.py"
check "lint + types + unit tests"        api_quality

finish
