#!/usr/bin/env bash
# Load the three demo institutions + demo users into the dev DB (idempotent).
#   scripts/seed.sh                 # all institutions
#   scripts/seed.sh --reset         # delete + recreate
#   scripts/seed.sh --institution abc-grammar-school
set -euo pipefail
cd "$(dirname "$0")/../api"
exec uv run python -m app.cli seed "$@"
