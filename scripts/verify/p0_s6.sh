#!/usr/bin/env bash
# Step 0.6 — user kickoff tasks (HANDOFF §3, §7). Checks local env only; Meta status is asked of the user.
#   bash scripts/verify/p0_s6.sh          # offline
#   LIVE=1 bash scripts/verify/p0_s6.sh   # also validates the Anthropic key + pinned models (free API)
STEP="p0_s6"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (user kickoff: env + keys)"

check ".env exists"                  test -f .env
check ".env is git-ignored and untracked" bash -c "git check-ignore -q .env && ! git ls-files --error-unmatch .env"
check ".env has every key name from .env.example" bash -c '
  for k in $(grep -oE "^[A-Z_]+=" .env.example | tr -d =); do grep -qE "^$k=" .env || { echo "missing $k"; exit 1; }; done'
if [[ "${LIVE:-0}" == "1" ]]; then
  check "provider keys set + Anthropic key/models valid" bash -c "cd api && uv run python -m scripts.check_keys --live"
else
  check "provider keys set (ANTHROPIC_API_KEY, VOYAGE_API_KEY)" bash -c "cd api && uv run python -m scripts.check_keys"
fi

finish
