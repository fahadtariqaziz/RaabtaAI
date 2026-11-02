#!/usr/bin/env bash
# Step 2.4 (HANDOFF §3).
STEP="p2_s4"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (embedding providers)"

check "fresh test DB migrated to head"   reset_test_db
check "embeddings: fake provider, voyage/bge over mocked HTTP, factory" \
  bash -c "cd api && uv run pytest tests/unit/test_embeddings.py"
if [[ "${RAABTA_BAKEOFF:-0}" == "1" ]]; then  # spends Voyage tokens (cents) — user opt-in
  check "seed + ingest demo docs"         seed_and_ingest_test_db
  check "bake-off subset (fake vs voyage)" bash -c "source scripts/verify/_lib.sh; kb_test_env; cd api && uv run python -m scripts.bakeoff_embeddings --providers fake,voyage --subset 12"
else
  echo "  - live bake-off skipped (set RAABTA_BAKEOFF=1 with VOYAGE_API_KEY in .env to run it)"
fi
check "lint + types + unit tests"        api_quality

finish
