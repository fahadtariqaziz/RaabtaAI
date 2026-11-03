#!/usr/bin/env bash
# Step 4.4 (HANDOFF §3): widget install + theming docs exist, and the snippet in the install guide
# is exactly what `GET /institution/widget-snippet` returns for the production script URL.
STEP="p4_s4"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (widget docs)"

check "docs/widget/install.md + theming.md exist" test -s docs/widget/install.md -a -s docs/widget/theming.md
check "install guide covers WordPress, Wix, custom HTML, CSP" \
  bash -c "grep -q '### WordPress' docs/widget/install.md && grep -q '### Wix' docs/widget/install.md && grep -q 'Custom HTML' docs/widget/install.md && grep -q 'Content-Security-Policy' docs/widget/install.md"
check "snippet in docs == widget-snippet output" \
  bash -c "cd '$ROOT/api' && WIDGET_SCRIPT_URL=https://cdn.raabta.ai/widget/v1/widget.js uv run python -c \"
from app.core.config import get_settings
from app.services.widget import snippet
s = snippet('abc-grammar-school', get_settings())
assert s in open('../docs/widget/install.md').read(), s
\""

finish
