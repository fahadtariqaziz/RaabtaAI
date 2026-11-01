#!/usr/bin/env bash
# Step 1.1 — core tables & Alembic baseline (HANDOFF §3).
STEP="p1_s1"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (core tables & Alembic baseline)"

export IT_MIGRATIONS_URL="postgresql+asyncpg://raabta:raabta@localhost:55432/raabta_test"
PSQL=(docker compose exec -T postgres psql -U raabta -d postgres -qc)

check "postgres up"                       docker compose up -d --wait postgres
check "fresh disposable test DB"          bash -c "${PSQL[*]} 'DROP DATABASE IF EXISTS raabta_test' && ${PSQL[*]} 'CREATE DATABASE raabta_test OWNER raabta'"
check "single alembic head"               bash -c "cd api && [[ \$(uv run alembic heads | wc -l | tr -d ' ') == 1 ]]"
check "migrations: roundtrip, no drift, constraints" bash -c "cd api && uv run pytest -m integration tests/integration/test_migrations.py"
check "dev DB migrated to head (make migrate)" make -s migrate
check "lint + types"                      bash -c "cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy"
check "unit tests still pass"             bash -c "cd api && uv run pytest"

finish
