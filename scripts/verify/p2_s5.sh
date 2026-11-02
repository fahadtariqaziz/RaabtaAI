#!/usr/bin/env bash
# Step 2.5 (HANDOFF §3).
STEP="p2_s5"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (hybrid search)"

check "fresh test DB migrated to head"   reset_test_db
check "search: roman urdu/urdu, fusion, isolation, exclusions, fallback" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_search.py"
check "seed + ingest demo docs into test DB" seed_and_ingest_test_db
check "retrieval eval gate (recall@5 >= 0.90, roman urdu >= 0.85)" \
  bash -c "source scripts/verify/_lib.sh; kb_test_env; cd api && uv run python -m evals.run_evals --suite retrieval"
check "lint + types + unit tests"        api_quality

finish
