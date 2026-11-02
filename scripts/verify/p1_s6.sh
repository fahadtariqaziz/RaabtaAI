#!/usr/bin/env bash
# Step 1.6 — audit log & usage rollup (HANDOFF §3).
STEP="p1_s6"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (audit log & usage rollup)"

check "fresh test DB migrated to head"   reset_test_db
check "audit: explicit + generic rows, /audit-log scoped, admin-only" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_audit.py"
check "usage: record_usage, local-day rollup idempotent, /usage" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_usage_rollup.py"
check "worker job rollup_usage_job runs (startup → job → shutdown)" bash -c "cd api && DATABASE_URL=\$IT_APP_DATABASE_URL uv run python -c '
import asyncio
from app.jobs.worker import WorkerSettings, rollup_usage_job, shutdown, startup
async def main():
    ctx = {}
    await startup(ctx)
    try:
        print(\"rows\", await rollup_usage_job(ctx, \"2027-02-10\"))
    finally:
        await shutdown(ctx)
    assert any(j.name.endswith(\"rollup_usage_job\") for j in WorkerSettings.cron_jobs)
asyncio.run(main())
'"
check "lint + types + unit tests"        api_quality

finish
