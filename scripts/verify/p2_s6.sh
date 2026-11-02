#!/usr/bin/env bash
# Step 2.6 (HANDOFF §3).
STEP="p2_s6"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (structured facts)"

check "fresh test DB migrated to head"   reset_test_db
check "facts: pkr parsing, xlsx mapping == seed.yaml, extractor replay" \
  bash -c "cd api && uv run pytest tests/unit/test_facts_unit.py"
check "facts: approval flow, facts_version, audit, supersede, extractor in pipeline" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_facts.py"
check "lint + types + unit tests"        api_quality

finish
