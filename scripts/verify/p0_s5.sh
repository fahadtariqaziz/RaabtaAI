#!/usr/bin/env bash
# Step 0.5 — docs & ADR scaffolding (minimal).
STEP="p0_s5"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (docs & ADR)"

check "ADR index + ADR 0001 exist" test -f docs/adr/README.md -a -f docs/adr/0001-free-hosting-netlify.md
check "README links PLAN/HANDOFF/CLAUDE" bash -c "grep -q 'docs/PLAN.md' README.md && grep -q 'HANDOFF.md' README.md && grep -q 'CLAUDE.md' README.md"
check "all relative links in docs resolve" bash -c '
  fail=0
  for f in README.md docs/adr/*.md; do
    for link in $(grep -oE "\]\([^)#:]+\)" "$f" | sed -E "s/^\]\(//; s/\)$//"); do
      [[ -e "$(dirname "$f")/$link" ]] || { echo "broken: $f -> $link"; fail=1; }
    done
  done
  exit $fail'

finish
