#!/usr/bin/env bash
# Step 4.2 (HANDOFF §3): widget bundle — typecheck, format, build dist/v1/widget.js, ≤ 30KB gz.
# Behaviour is exercised in a real browser by p4_s3 (e2e over the embed test pages).
STEP="p4_s2"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (widget bundle)"

check "widget: typecheck"               pnpm -C widget typecheck
check "widget: prettier"                npx prettier --check widget/src widget/scripts
check "widget: build dist/v1/widget.js" bash -c "pnpm -C widget build && test -f widget/dist/v1/widget.js"
check "widget: size <= 30KB gz"         pnpm -C widget size

finish
