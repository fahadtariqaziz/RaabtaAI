#!/usr/bin/env bash
# Step 4.3 (HANDOFF §3): bundle served by the API + embed test pages, driven in the system
# Chrome (playwright-core, no browser download): plain / WordPress-like / RTL-mobile pages.
# `--headed` shows the browser; screenshots land in /tmp/raabta-shots.
STEP="p4_s3"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (widget served by API + e2e)"
trap stop_demo_api EXIT

check "fresh test DB migrated to head"   reset_test_db
check "seed + ingest demo institutions into the test DB" seed_and_ingest_test_db
check "widget bundle built"              pnpm -C widget build
check "demo API up on :$DEMO_API_PORT"  start_demo_api
check "widget.js served with version + cache headers" \
  bash -c "curl -sfI '$DEMO_API/widget/v1/widget.js' | grep -qi '^x-widget-version' && \
    curl -sfI '$DEMO_API/widget/v1/widget.js' | grep -qi '^cache-control: public'"
check "embed test pages served (dev only)" \
  bash -c "for p in plain wordpress-like rtl; do curl -sf '$DEMO_API/widget/test/'\$p.html >/dev/null || exit 1; done"
flush_test_redis
check "e2e (Chrome): ask → answer, slots, lead form, CSS isolation, RTL, mobile" \
  bash -c "cd '$ROOT/widget' && WIDGET_BASE='$DEMO_API' node scripts/e2e.mjs --shots /tmp/raabta-shots ${1:-}"

finish
