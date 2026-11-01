#!/usr/bin/env bash
# Step 0.1 — repo scaffold & tooling (HANDOFF §3).
STEP="p0_s1"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (repo scaffold & tooling)"

check "_lib.sh present"            test -f scripts/verify/_lib.sh
check "root files present"         test -f Makefile -a -f .editorconfig -a -f .gitignore -a -f .env.example -a -f pnpm-workspace.yaml
check ".env is git-ignored"        git check-ignore -q .env
check "api: uv sync"               bash -c "cd api && uv sync --frozen"
check "api: ruff lint"             bash -c "cd api && uv run ruff check ."
check "api: ruff format"           bash -c "cd api && uv run ruff format --check ."
check "api: mypy strict"           bash -c "cd api && uv run mypy"
check "api: pytest"                bash -c "cd api && uv run pytest"
check "admin: lint"                pnpm -C admin lint
check "admin: typecheck"           pnpm -C admin typecheck
check "admin: build"               pnpm -C admin build
check "widget: typecheck"          pnpm -C widget typecheck
check "widget: build dist/widget.js" bash -c "pnpm -C widget build && test -f widget/dist/widget.js"
check "widget: size <= 30KB gz"    pnpm -C widget size

finish
