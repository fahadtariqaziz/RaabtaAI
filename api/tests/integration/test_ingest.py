"""Step 2.8 — pipeline statuses, failure capture + resume, atomic re-index/supersede, worker job."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.kb import Chunk, Document
from app.seeds.schema import SEEDS_DIR
from tests.support import Factory, as_tenant, auth_headers, ingest, run, upload

pytestmark = pytest.mark.integration
DOCS = SEEDS_DIR / "abc_grammar_school" / "docs"


def _doc(client: TestClient, h: dict[str, str], doc_id: str) -> dict[str, object]:
    body: dict[str, object] = client.get(f"/api/v1/kb/documents/{doc_id}", headers=h).json()
    return body


def test_pipeline_reaches_ready_with_chunks_embeddings_and_meta(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    doc = upload(client, h, DOCS / "fee_structure.xlsx").json()
    assert run(ingest(it_settings, t.id, uuid.UUID(doc["id"]))) == "ready"
    got = _doc(client, h, doc["id"])
    assert got["status"] == "ready" and got["pages"] == 2 and got["error"] is None
    meta = got["meta"]
    assert isinstance(meta, dict)
    assert meta["chunk_count"] == 2 and meta["facts"] == {"fee_items": 16, "transport_routes": 4}
    chunks = client.get(f"/api/v1/kb/documents/{doc['id']}/chunks", headers=h).json()
    assert [c["page"] for c in chunks] == [1, 2]
    assert all(c["embedded"] and not c["suspicious"] for c in chunks)
    # idempotent: running again is a no-op
    assert run(ingest(it_settings, t.id, uuid.UUID(doc["id"]))) == "ready"


def test_failure_is_captured_and_retry_resumes(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    doc = upload(client, h, b"%PDF-1.7\nnot a real pdf", filename="broken.pdf").json()
    assert run(ingest(it_settings, t.id, uuid.UUID(doc["id"]))) == "failed"
    got = _doc(client, h, doc["id"])
    assert got["status"] == "failed"
    assert str(got["error"]).startswith("parsing: cannot open PDF")
    assert got["meta"] == {"failed_stage": "parsing"}
    # re-index of a failed document resumes on the same row (still fails: same bytes)
    r = client.post(f"/api/v1/kb/documents/{doc['id']}/reindex", headers=h)
    assert r.status_code == 202 and r.json()["id"] == doc["id"]


def test_reindex_creates_new_version_and_supersedes_atomically(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    v1 = upload(client, h, DOCS / "prospectus.docx").json()
    run(ingest(it_settings, t.id, uuid.UUID(v1["id"])))
    r = client.post(f"/api/v1/kb/documents/{v1['id']}/reindex", headers=h)
    assert r.status_code == 202
    v2 = r.json()
    assert (v2["version"], v2["supersedes_id"], v2["status"]) == (2, v1["id"], "uploaded")
    # while v2 is processing, v1 keeps serving
    assert _doc(client, h, v1["id"])["status"] == "ready"
    assert client.post(f"/api/v1/kb/documents/{v1['id']}/reindex", headers=h).status_code == 409
    run(ingest(it_settings, t.id, uuid.UUID(v2["id"])))
    assert _doc(client, h, v1["id"])["status"] == "superseded"
    assert _doc(client, h, v2["id"])["status"] == "ready"

    async def counts(session: AsyncSession) -> dict[str, int]:
        rows = await session.execute(
            select(Chunk.document_id, func.count()).group_by(Chunk.document_id)
        )
        return {str(k): v for k, v in rows.all()}

    by_doc: dict[str, int] = run(as_tenant(it_settings, t.id, counts))
    assert v1["id"] not in by_doc and by_doc[v2["id"]] >= 1
    listed = client.get("/api/v1/kb/documents", headers=h).json()
    assert [d["id"] for d in listed] == [v2["id"]]
    history = client.get("/api/v1/kb/documents?include_superseded=true", headers=h).json()
    assert [d["version"] for d in history] == [2, 1]


def test_worker_job_runs_pipeline_with_lock(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    from redis.asyncio import Redis

    from app.jobs.worker import ingest_document_job
    from app.kb.blobstore import make_blobstore
    from app.kb.embeddings import make_provider
    from app.kb.ingest import IngestDeps

    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    doc = upload(client, h, DOCS / "fee_structure.xlsx").json()

    async def go() -> tuple[str, str]:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from app.db.session import make_sessionmaker

        engine = create_async_engine(it_settings.database_url, poolclass=NullPool)
        redis = Redis.from_url(it_settings.redis_url)
        ctx = {
            "redis": redis,
            "ingest": IngestDeps(
                make_sessionmaker(engine),
                make_blobstore(it_settings),
                it_settings,
                make_provider(it_settings),
            ),
        }
        try:
            await redis.set(f"kb:ingest-lock:{doc['id']}", "1")
            locked = await ingest_document_job(ctx, str(t.id), doc["id"])
            await redis.delete(f"kb:ingest-lock:{doc['id']}")
            done = await ingest_document_job(ctx, str(t.id), doc["id"])
            return locked, done
        finally:
            await redis.aclose()
            await engine.dispose()

    assert run(go()) == ("locked", "ready")

    async def status(session: AsyncSession) -> str | None:
        return await session.scalar(
            select(Document.status).where(Document.id == uuid.UUID(doc["id"]))
        )

    assert run(as_tenant(it_settings, t.id, status)) == "ready"
