#!/usr/bin/env bash
# Step 3.9 (HANDOFF §3). Offline: datasets, graders, harness plumbing (scripted LLM) on the seeded
# test DB, and cassette replay of router/tone if recorded. `--live` = first live run (spends
# ~$15–25; needs ANTHROPIC_API_KEY and user approval) — records cassettes + writes reports.
STEP="p3_s9"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (eval harness)"

check "fresh test DB migrated to head"   reset_test_db
check "datasets: sizes, schema, PKR expectations ⊂ seed facts" \
  bash -c "cd api && uv run python -m evals.run_evals --suite agent --validate"
check "graders, metrics/gates, report format, classifier plumbing" \
  bash -c "cd api && uv run pytest tests/unit/test_evals.py"
check "seed + ingest demo institutions into the test DB" seed_and_ingest_test_db
check "agent suites end-to-end through the graph (scripted LLM, no spend)" \
  bash -c "cd '$ROOT/api' && uv run pytest -m integration tests/integration/test_eval_harness.py"
for s in router tone; do
  if [[ -f "$ROOT/api/evals/cassettes/suites/$s.json" ]]; then
    check "$s replay (recorded cassettes)" \
      bash -c "cd '$ROOT/api' && uv run python -m evals.run_evals --suite $s --mode replay"
  fi
done
if [[ "${1:-}" == "--live" ]]; then
  check "LIVE: all agent suites, record cassettes, write reports" \
    bash -c "cd '$ROOT/api' && DATABASE_URL='$IT_APP_DATABASE_URL' REDIS_URL='$IT_REDIS_URL' \
      EMBEDDING_PROVIDER=fake uv run python -m evals.run_evals --suite agent --mode record --report"
fi
check "lint + types + unit tests"        api_quality

finish
