#!/usr/bin/env bash
# Step 2.3 (HANDOFF §3).
STEP="p2_s3"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (chunking & normalization)"

check "fresh test DB migrated to head"   reset_test_db
check "chunking: sizes, overlap, page refs, table rows, normalization, lang, injection" \
  bash -c "cd api && uv run pytest tests/unit/test_chunking.py"
check "lint + types + unit tests"        api_quality

finish
