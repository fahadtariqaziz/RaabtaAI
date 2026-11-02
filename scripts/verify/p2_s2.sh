#!/usr/bin/env bash
# Step 2.2 (HANDOFF §3).
STEP="p2_s2"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (parsers)"

check "fresh test DB migrated to head"   reset_test_db
check "parsers: pdf pages/headings/flags, docx + urdu, xlsx/csv rows, sniffing" \
  bash -c "cd api && uv run pytest tests/unit/test_parsers.py"
check "lint + types + unit tests"        api_quality

finish
