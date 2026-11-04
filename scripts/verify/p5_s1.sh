#!/usr/bin/env bash
# Step 5.1 (HANDOFF §3): admin foundation — lint, types, production build, generated OpenAPI
# client in sync with the API, EN/UR message catalogs have identical keys. UI behaviour (login,
# guard, RTL, dark mode) is exercised by the browser e2e in p5_s11.
STEP="p5_s1"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (admin foundation)"

check "admin lint"                         pnpm -C admin lint
check "admin typecheck"                    pnpm -C admin typecheck
check "admin prettier"                     npx prettier --check admin/src admin/scripts
check "OpenAPI TS client in sync with the API (pnpm -C admin gen:api)" bash -c "
  before=\$(cat admin/src/lib/api/schema.d.ts | shasum); pnpm -C admin gen:api >/dev/null &&
  [ \"\$before\" = \"\$(cat admin/src/lib/api/schema.d.ts | shasum)\" ]"
check "EN/UR message catalogs have the same keys" python3 - <<'PY'
import json
def keys(d, p=""):
    out = set()
    for k, v in d.items():
        out |= keys(v, p + k + ".") if isinstance(v, dict) else {p + k}
    return out
en = keys(json.load(open("admin/src/messages/en.json")))
ur = keys(json.load(open("admin/src/messages/ur.json")))
assert en == ur, en ^ ur
PY
check "admin production build"             pnpm -C admin build

finish
