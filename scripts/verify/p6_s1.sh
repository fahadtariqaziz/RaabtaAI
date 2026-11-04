#!/usr/bin/env bash
# Step 6.1 (👤 user): live Meta checks — needs META_ACCESS_TOKEN, META_PHONE_NUMBER_ID,
# META_VERIFY_TOKEN, META_WABA_ID in .env and a public URL for the webhook (ngrok/cloudflared).
#   bash scripts/verify/p6_s1.sh https://<public-host>/api/v1/webhooks/whatsapp
# Expected: "✔ number +92… · name '<Institution>' · quality GREEN", "✔ webhook verify round-trip".
STEP="p6_s1"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (live Meta: phone number + webhook handshake)"

if [[ -z "${1:-}" ]]; then
  echo "  usage: bash scripts/verify/p6_s1.sh <public webhook url>"; exit 1
fi
check "Graph API: phone number, display name, quality; webhook verify via $1" \
  bash -c "cd '$ROOT/api' && uv run python -m scripts.wa_check --webhook '$1' --templates"

finish
