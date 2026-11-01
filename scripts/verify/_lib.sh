#!/usr/bin/env bash
# Shared helpers for scripts/verify/pN_sM.sh. Source this file; do not run it.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STEP="${STEP:-unknown}"
FAILED=0

check() { # check "description" command...
  local desc="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then
    echo "  ✔ $desc"
  else
    echo "  ✘ $desc"
    echo "$out" | tail -20 | sed 's/^/      /'
    FAILED=1
  fi
}

finish() {
  if [[ "$FAILED" -eq 0 ]]; then
    echo "VERIFY $STEP: OK"; exit 0
  else
    echo "VERIFY $STEP: FAILED"; exit 1
  fi
}
