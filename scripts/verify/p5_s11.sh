#!/usr/bin/env bash
# Step 5.11 (+ UI of 5.1–5.10): built admin against the seeded demo API, driven in the system
# Chrome — login/guard, every page, inbox takeover flow, leads, settings, Urdu RTL, dark mode,
# mobile inbox, superadmin impersonation, axe (no serious/critical violations on any page).
# `--headed` shows the browser; screenshots land in /tmp/raabta-admin-shots.
STEP="p5_s11"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (admin UI e2e + accessibility)"
trap 'stop_admin; stop_demo_api' EXIT

check "fresh test DB migrated to head"   reset_test_db
check "seed + ingest demo institutions into the test DB" seed_and_ingest_test_db
flush_test_redis
check "demo API up on :$DEMO_API_PORT"  start_demo_api
check "admin built + started on :$ADMIN_PORT (proxying the demo API)" start_admin
check "e2e (Chrome): pages, inbox takeover, leads, settings, RTL, dark, mobile, superadmin, axe" \
  bash -c "cd '$ROOT/admin' && ADMIN_BASE='$ADMIN' API_BASE='$DEMO_API' node scripts/e2e.mjs --shots /tmp/raabta-admin-shots ${1:-}"

finish
