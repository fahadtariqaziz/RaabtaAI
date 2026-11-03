#!/usr/bin/env bash
# Step 3.10 (HANDOFF §3). Offline: CLI runner + transcript rendering with a scripted LLM.
# `--live` runs the 9 demo conversations against the seeded test DB (spends ~$1; needs approval)
# and writes transcripts to docs/demo/ (+ cassettes for replay).
STEP="p3_s10"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (local chat CLI & demo transcripts)"

check "fresh test DB migrated to head"   reset_test_db
check "seed + ingest demo institutions into the test DB" seed_and_ingest_test_db
check "scripted conversation → transcript (route, tools, check, citations)" \
  bash -c "cd '$ROOT/api' && uv run pytest -m integration tests/integration/test_chat_cli.py"
if [[ "${1:-}" == "--live" ]]; then
  check "LIVE: 9 demo conversations, expected tools called, transcripts written" \
    bash -c "cd '$ROOT/api' && DATABASE_URL='$IT_APP_DATABASE_URL' REDIS_URL='$IT_REDIS_URL' \\
      EMBEDDING_PROVIDER=fake uv run python -m scripts.chat --script ../docs/demo/scripts.yaml \\
      --mode record --out ../docs/demo"
fi
check "lint + types + unit tests"        api_quality

finish
