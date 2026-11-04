#!/usr/bin/env bash
# Steps 6.2–6.8 (consolidated, like Phase 5): the WhatsApp pipeline with zero spend — FakeLLM,
# FakeSTT and a recording Graph API (httpx.MockTransport):
#   unit: signature, payload shapes, status order, 24h window, compose, templates, policy gate
#         (quiet hours / Jumma / weekly cap / opt-out words), Graph retries, STT confidence;
#   integration: webhook verify/403/idempotency → worker job → AI reply delivered (privacy line)
#         → statuses → voice notes → opt-out → window refusal → widget-code link → follow-ups
#         (quiet hours, template send, cap, staff mode) → booking reminder → daily summary →
#         templates API (seed/submit/status webhook/sync);
#   isolation over every route (templates + webhook classified); lint/types/unit.
# The admin side (templates page, inbox window banner, WhatsApp settings) is in p5_s11.
STEP="p6_s2"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (WhatsApp channel: webhook, sender, window, voice, templates, follow-ups, policy)"

check "fresh test DB migrated to head (0005)" reset_test_db
check "migration 0005 round-trips (downgrade -1 → upgrade head)" \
  bash -c "cd '$ROOT/api' && uv run alembic -x 'url=$IT_MIGRATIONS_URL' downgrade -1 && uv run alembic -x 'url=$IT_MIGRATIONS_URL' upgrade head"
check "unit: webhook, window, compose, templates, policy gate, client, STT" \
  bash -c "cd '$ROOT/api' && uv run pytest tests/unit/test_whatsapp_units.py -q"
flush_test_redis
check "integration: webhook → worker → delivery, voice, opt-out, window, follow-ups, templates" \
  bash -c "cd '$ROOT/api' && uv run pytest -m integration tests/integration/test_whatsapp.py -q"
check "isolation: every route incl. templates + webhook (full log: /tmp/raabta-isolation.log)" \
  bash -c "cd '$ROOT/api' && uv run pytest -m isolation tests/isolation -q -p no:warnings > /tmp/raabta-isolation.log 2>&1 || { grep -E 'FAILED|before:|after:' /tmp/raabta-isolation.log | sed 's/^/✘ /' | cut -c1-300; exit 1; }"
check "worker imports with the WhatsApp jobs + crons" \
  bash -c "cd '$ROOT/api' && uv run python -c 'from app.jobs.worker import WorkerSettings as W; n={f.__name__ for f in W.functions}; assert {\"whatsapp_event_job\",\"deliver_message_job\",\"dispatch_followups_job\",\"daily_summary_job\"} <= n; assert len(W.cron_jobs) == 3'"
check "lint + types + unit tests" api_quality

finish
