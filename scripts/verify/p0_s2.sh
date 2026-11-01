#!/usr/bin/env bash
# Step 0.2 — docker-compose & dev scripts (HANDOFF §3).
# Brings up postgres+redis, builds and runs the full app profile, then checks everything is healthy.
STEP="p0_s2"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (docker-compose & dev scripts)"

PSQL=(docker compose exec -T postgres psql -U raabta -d raabta -tAc)

check "docker daemon running"          docker info
check "compose file valid"             docker compose --profile app config -q
check "postgres + redis healthy"       docker compose up -d --wait postgres redis
check "extensions vector,pg_trgm,unaccent" bash -c "[[ \$(${PSQL[*]} \"select count(*) from pg_extension where extname in ('vector','pg_trgm','unaccent')\") == 3 ]]"
check "runtime role raabta_app is not superuser/bypassrls" bash -c "[[ \$(${PSQL[*]} \"select rolsuper or rolbypassrls from pg_roles where rolname='raabta_app'\") == f ]]"
check "redis PING"                     bash -c "[[ \$(docker compose exec -T redis redis-cli ping) == PONG ]]"
check "build api/worker/admin images"  docker compose --profile app build
check "app profile up (api healthy)"   docker compose --profile app up -d --wait
check "api /healthz via container"     bash -c "curl -fsS localhost:8000/healthz | grep -q '\"ok\"'"
check "admin serves on :3000"          bash -c "curl -fsS -o /dev/null localhost:3000"
check "worker consumes queue (ping job)" bash -c "cd api && REDIS_URL=redis://localhost:56379/0 uv run python -c '
import asyncio
from arq import create_pool
from arq.connections import RedisSettings
async def main():
    pool = await create_pool(RedisSettings.from_dsn(\"redis://localhost:56379/0\"))
    job = await pool.enqueue_job(\"ping\")
    assert await job.result(timeout=20) == \"pong\"
asyncio.run(main())
'"
check "dev.sh is valid bash"           bash -n scripts/dev.sh

# Leave postgres/redis running for development; stop the app containers.
docker compose --profile app stop api worker admin >/dev/null 2>&1
finish
