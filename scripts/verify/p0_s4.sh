#!/usr/bin/env bash
# Step 0.4 — minimal CI (HANDOFF §3). Lints the workflow and runs the same commands locally.
STEP="p0_s4"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (minimal CI)"

check "actionlint (via docker) on workflows" docker run --rm -v "$ROOT:/repo" -w /repo rhysd/actionlint:latest
check "api job locally: frozen sync"  bash -c "cd api && uv sync --frozen"
check "api job locally: lint/types/tests" bash -c "cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy && env -u ANTHROPIC_API_KEY -u VOYAGE_API_KEY uv run pytest"
check "web job locally: frozen install" pnpm install --frozen-lockfile
check "web job locally: admin lint/types/build" bash -c "pnpm -C admin lint && pnpm -C admin typecheck && pnpm -C admin build"
check "web job locally: widget types/build/size" bash -c "pnpm -C widget typecheck && pnpm -C widget build && pnpm -C widget size"

finish
