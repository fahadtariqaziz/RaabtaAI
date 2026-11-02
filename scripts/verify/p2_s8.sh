#!/usr/bin/env bash
# Step 2.8 (HANDOFF §3).
STEP="p2_s8"
source "$(dirname "$0")/_lib.sh"
cd "$ROOT"
echo "Verifying $STEP (ingestion pipeline & KB evals)"

check "fresh test DB migrated to head"   reset_test_db
check "pipeline: statuses, failure + resume, atomic supersede, worker job lock" \
  bash -c "cd api && uv run pytest -m integration tests/integration/test_ingest.py"
check "ingest-seeds: all 6 demo docs reach ready" seed_and_ingest_test_db
check "ingest-seeds is idempotent (second run, same fact counts)" bash -c "source scripts/verify/_lib.sh; kb_test_env; cd api && a=\$(docker compose exec -T postgres psql -U raabta -d raabta_test -Atc \"select count(*) from fee_items\") && uv run python -m app.cli ingest-seeds >/dev/null && b=\$(docker compose exec -T postgres psql -U raabta -d raabta_test -Atc \"select count(*) from fee_items\") && echo \$a \$b && [ \"\$a\" = \"\$b\" ] && [ \"\$a\" -gt 0 ]"
check "arq worker (burst) consumes an enqueued ingest job" bash -c "source scripts/verify/_lib.sh; kb_test_env; cd api && uv run python - <<PY
import asyncio
from sqlalchemy import select
from arq.connections import ArqRedis
from app.core.config import get_settings
from app.core.tenancy import admin_session, tenant_session
from app.db.session import make_engine, make_sessionmaker
from app.kb.blobstore import make_blobstore
from app.kb.ingest import enqueue_ingest
from app.models.core import Institution
from app.services.kb_documents import create_document
async def main():
    s = get_settings(); e = make_engine(s.database_url); sm = make_sessionmaker(e)
    async with admin_session(sm) as x:
        inst = await x.scalar(select(Institution.id).where(Institution.slug == \"abc-grammar-school\"))
    async with tenant_session(sm, inst) as x:
        d = await create_document(x, make_blobstore(s), institution_id=inst, user_id=None,
            data=b\"Notice,Detail\\nSports day,Friday 10:00\\n\", filename=\"notice.csv\", title=\"Notice\")
    r = ArqRedis.from_url(s.redis_url); await enqueue_ingest(r, inst, d.id); await r.aclose()
    open(\"/tmp/raabta_p2s8_doc\", \"w\").write(f\"{inst} {d.id}\"); await e.dispose()
asyncio.run(main())
PY
uv run arq app.jobs.worker.WorkerSettings --burst >/dev/null 2>&1
read inst doc < /tmp/raabta_p2s8_doc
st=\$(docker compose exec -T postgres psql -U raabta -d raabta_test -Atc \"select status from documents where id = '\$doc'\")
echo status=\$st; [ \"\$st\" = ready ]"
check "retrieval eval gate on ingested seeds" \
  bash -c "source scripts/verify/_lib.sh; kb_test_env; cd api && uv run python -m evals.run_evals --suite retrieval"
check "lint + types + unit tests"        api_quality

finish
