#!/usr/bin/env bash
# Step 1.5 — seed three demo institutions (HANDOFF §3).
STEP="p1_s5"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (demo seeds)"

seed_twice() { # CLI against the test DB twice; outputs must match (idempotent)
  local a b
  a="$(DATABASE_URL=$IT_APP_DATABASE_URL scripts/seed.sh)" || return 1
  b="$(DATABASE_URL=$IT_APP_DATABASE_URL scripts/seed.sh)" || return 1
  echo "$b"
  [[ "$a" == "$b" ]] && [[ $(grep -c '^seeded ' <<<"$b") == 3 ]]
}

check "fresh test DB migrated to head"        reset_test_db
check "seed CLI twice → same result, 3 institutions" seed_twice
check "seed counts, docs on disk, demo logins" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_seeds.py"
check "seed docs present (XLSX + DOCX × 3)"   bash -c "[[ \$(ls api/seeds/*/docs/{fee_structure.xlsx,prospectus.docx} | wc -l | tr -d ' ') == 6 ]]"
check "lint + types + unit tests"             api_quality

finish
