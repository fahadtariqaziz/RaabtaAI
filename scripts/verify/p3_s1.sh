#!/usr/bin/env bash
# Step 3.1 (HANDOFF §3). Live smoke only with --live (spends cents; needs ANTHROPIC_API_KEY).
STEP="p3_s1"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (Claude client wrapper)"

check "wrapper branches (mocked SDK): fallback, effort, stop_reason, retries, cache, cassettes" \
  bash -c "cd api && uv run pytest tests/unit/test_claude_wrapper.py tests/unit/test_facts_unit.py"
if [[ "${1:-}" == "--live" ]]; then
  check "live smoke: second identical-prefix call reads the cache" \
    bash -c "cd api && uv run python -m scripts.llm_smoke"
fi
check "lint + types + unit tests"        api_quality

finish
