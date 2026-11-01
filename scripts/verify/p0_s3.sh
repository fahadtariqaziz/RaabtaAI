#!/usr/bin/env bash
# Step 0.3 — config, model registry, logging, /readyz (HANDOFF §3).
STEP="p0_s3"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (config, model registry, logging, readyz)"

export IT_DATABASE_URL="postgresql+asyncpg://raabta_app:raabta_app@localhost:55432/raabta"
export IT_REDIS_URL="redis://localhost:56379/0"

check "unit: config, registry, health/readyz" bash -c "cd api && uv run pytest tests/unit/test_config.py tests/unit/test_models_registry.py tests/unit/test_health.py"
check "missing DATABASE_URL -> clear startup error" bash -c "cd api && out=\$(DATABASE_URL= uv run python -c 'import app.main' 2>&1); [[ \$? -ne 0 ]] && grep -q 'DATABASE_URL: Field required' <<<\"\$out\" && ! grep -q 'input_value' <<<\"\$out\""
check "postgres + redis up"            docker compose up -d --wait postgres redis
check "integration: /readyz 200 vs compose (as raabta_app)" bash -c "cd api && uv run pytest -m integration tests/integration/test_readyz.py"
check "lint + types"                   bash -c "cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy"

finish
