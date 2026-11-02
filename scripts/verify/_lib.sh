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
