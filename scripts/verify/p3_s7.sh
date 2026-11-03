#!/usr/bin/env bash
# Step 3.7 (HANDOFF §3). Guardrails eval replay runs once cassettes are recorded (3.9 live run).
STEP="p3_s7"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (guardrails)"

check "guards: opt-out, injection, script, numeric grounding, repair format, rate/daily caps" \
  bash -c "cd api && uv run pytest tests/unit/test_guards.py"
check "guardrails dataset (40 cases) validates" \
  bash -c "cd api && uv run python -m evals.run_evals --suite guardrails --validate"
check "lint + types + unit tests"        api_quality

finish
