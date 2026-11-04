#!/usr/bin/env bash
# Shared helpers for scripts/verify/pN_sM.sh. Source this file; do not run it.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STEP="${STEP:-unknown}"
FAILED=0

check() { # check "description" command...
  local desc="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then
    echo "  ✔ $desc"
  else
    echo "  ✘ $desc"
    # Failing sub-checks first (they can scroll out of the tail), then the tail for context.
    echo "$out" | grep -E '✘' | head -20 | sed 's/^/      /'
    echo "$out" | tail -20 | sed 's/^/      /'
    FAILED=1
  fi
}

finish() {
  if [[ "$FAILED" -eq 0 ]]; then
    echo "VERIFY $STEP: OK"; exit 0
  else
    echo "VERIFY $STEP: FAILED"; exit 1
  fi
}

# Integration test env: disposable `raabta_test` DB (owner role for migrations, runtime role
# `raabta_app` for the app → RLS enforced) and Redis db 15.
export IT_MIGRATIONS_URL="postgresql+asyncpg://raabta:raabta@localhost:55432/raabta_test"
export IT_APP_DATABASE_URL="postgresql+asyncpg://raabta_app:raabta_app@localhost:55432/raabta_test"
export IT_REDIS_URL="redis://localhost:56379/15"

reset_test_db() { # recreate raabta_test and migrate it to head
  cd "$ROOT" && docker compose up -d --wait postgres redis >/dev/null &&
    docker compose exec -T postgres psql -U raabta -d postgres -qc 'DROP DATABASE IF EXISTS raabta_test' &&
    docker compose exec -T postgres psql -U raabta -d postgres -qc 'CREATE DATABASE raabta_test OWNER raabta' &&
    (cd api && uv run alembic -x "url=$IT_MIGRATIONS_URL" upgrade head)
}

api_quality() { # ruff + format + mypy + unit tests
  cd "$ROOT/api" && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
}

# CLI/worker env against the disposable test DB (fake embeddings → no spend; temp blob dir).
kb_test_env() {
  export DATABASE_URL="$IT_APP_DATABASE_URL" REDIS_URL="$IT_REDIS_URL" EMBEDDING_PROVIDER=fake \
    KB_FACTS_LLM=0 KB_VISION_OCR=0 BLOB_DIR="${BLOB_DIR:-/tmp/raabta-blobs-test}"
}

seed_and_ingest_test_db() { # demo institutions + their documents through the KB pipeline
  kb_test_env && cd "$ROOT/api" && uv run python -m app.cli seed >/dev/null &&
    uv run python -m app.cli ingest-seeds
}

# Phase 4: API on the seeded test DB with the zero-spend demo agent (AGENT_LLM=demo).
DEMO_API_PORT="${DEMO_API_PORT:-8010}"
DEMO_API="http://localhost:$DEMO_API_PORT"
start_demo_api() {
  stop_demo_api
  # Redirect the whole background subshell (not just uv): otherwise it keeps check()'s $(...)
  # pipe open and the check never returns.
  (kb_test_env && cd "$ROOT/api" && ENV=test AGENT_LLM=demo \
    exec uv run uvicorn app.main:app --port "$DEMO_API_PORT") </dev/null >/tmp/raabta-demo-api.log 2>&1 &
  for _ in $(seq 1 60); do curl -sf "$DEMO_API/healthz" >/dev/null && return 0; sleep 0.5; done
  tail -20 /tmp/raabta-demo-api.log; return 1
}
stop_demo_api() { pkill -f "uvicorn app.main:app --port $DEMO_API_PORT" 2>/dev/null; sleep 0.5; true; }
flush_test_redis() { cd "$ROOT" && docker compose exec -T redis redis-cli -n 15 flushdb >/dev/null; }

# Phase 5: the built admin (`next start`) proxying the demo API. Rewrites are baked at build time,
# so the admin is built with API_URL pointing at the demo API.
ADMIN_PORT="${ADMIN_PORT:-3010}"
ADMIN="http://localhost:$ADMIN_PORT"
start_admin() {
  stop_admin
  (cd "$ROOT/admin" && API_URL="$DEMO_API" pnpm build >/tmp/raabta-admin-build.log 2>&1) || {
    tail -30 /tmp/raabta-admin-build.log; return 1; }
  (cd "$ROOT/admin" && PORT="$ADMIN_PORT" exec pnpm start) </dev/null >/tmp/raabta-admin.log 2>&1 &
  for _ in $(seq 1 60); do curl -sf -o /dev/null "$ADMIN/login" && return 0; sleep 0.5; done
  tail -20 /tmp/raabta-admin.log; return 1
}
stop_admin() { pkill -f "next start" 2>/dev/null; pkill -f "next-server" 2>/dev/null; sleep 0.5; true; }
