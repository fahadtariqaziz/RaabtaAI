"""Step 2.1 — upload (sniff, cap, dedupe, versioning), list/get/delete, status machine, RBAC."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.seeds.schema import SEEDS_DIR
from tests.support import Factory, auth_headers, run, upload

pytestmark = pytest.mark.integration
DOCS = SEEDS_DIR / "abc_grammar_school" / "docs"


def test_upload_seed_files_list_get_and_blob_stored(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    r1 = upload(client, h, DOCS / "fee_structure.xlsx", title="Fee structure")
    r2 = upload(client, h, DOCS / "prospectus.docx")
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    doc = r1.json()
    assert (doc["kind"], doc["status"], doc["version"], doc["title"]) == (
        "xlsx",
        "uploaded",
        1,
        "Fee structure",
    )
    assert r2.json()["title"] == "prospectus"  # default title = filename stem
    assert (it_settings.blob_dir / f"{t.id}/documents/{doc['id']}/original.xlsx").is_file()
    listed = client.get("/api/v1/kb/documents", headers=h).json()
    assert {d["id"] for d in listed} == {doc["id"], r2.json()["id"]}
    staff = auth_headers(client, t.emails["staff"], t.id)
    assert client.get(f"/api/v1/kb/documents/{doc['id']}", headers=staff).json()["id"] == doc["id"]
    rows = client.get("/api/v1/audit-log?entity=document", headers=h).json()
    assert {r["action"] for r in rows} == {"kb.document.upload"}


def test_rejects_unsupported_and_duplicates_and_staff(client: TestClient, factory: Factory) -> None:
    t = factory.tenant()
    h = auth_headers(client, t.emails["owner"], t.id)
    exe = upload(client, h, b"MZ\x90\x00" + b"\x00" * 64, filename="fees.pdf")
    assert exe.status_code == 415
    first = upload(client, h, DOCS / "fee_structure.xlsx")
    dup = upload(client, h, DOCS / "fee_structure.xlsx", title="Another title")
    assert dup.status_code == 409
    assert dup.json()["detail"]["document_id"] == first.json()["id"]
    staff = auth_headers(client, t.emails["staff"], t.id)
    assert upload(client, staff, DOCS / "prospectus.docx").status_code == 403


def test_size_cap(it_settings: Settings, factory: Factory) -> None:
    small = it_settings.model_copy(update={"kb_max_upload_mb": 1})
    with TestClient(create_app(small)) as c:
        t = factory.tenant()
        h = auth_headers(c, t.emails["admin"], t.id)
        big = b"class,fee\n" + b"Class 1,1000\n" * 100_000  # ~1.3 MB
        r = upload(c, h, big, filename="fees.csv")
        assert r.status_code == 413


def test_same_title_bumps_version_and_links_previous(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    from tests.support import ingest

    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    v1 = upload(
        client, h, b"Class,Fee head,Amount\nClass 1,Tuition fee,11000\n", "fees.csv", "Fees"
    )
    # previous version still processing → refuse a new version
    early = upload(
        client, h, b"Class,Fee head,Amount\nClass 1,Tuition fee,11500\n", "f.csv", "Fees"
    )
    assert early.status_code == 409
    import uuid

    assert run(ingest(it_settings, t.id, uuid.UUID(v1.json()["id"]))) == "ready"
    v2 = upload(client, h, b"Class,Fee head,Amount\nClass 1,Tuition fee,11500\n", "f.csv", "Fees")
    assert v2.status_code == 201, v2.text
    assert (v2.json()["version"], v2.json()["supersedes_id"]) == (2, v1.json()["id"])


def test_delete_removes_row_chunks_and_blob(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    import uuid

    from tests.support import ingest

    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    doc = upload(client, h, DOCS / "prospectus.docx").json()
    run(ingest(it_settings, t.id, uuid.UUID(doc["id"])))
    assert client.get(f"/api/v1/kb/documents/{doc['id']}/chunks", headers=h).json()
    r = client.delete(f"/api/v1/kb/documents/{doc['id']}", headers=h)
    assert r.status_code == 204
    assert client.get(f"/api/v1/kb/documents/{doc['id']}", headers=h).status_code == 404
    assert client.get(f"/api/v1/kb/documents/{doc['id']}/chunks", headers=h).status_code == 404
    assert not (it_settings.blob_dir / f"{t.id}/documents/{doc['id']}/original.docx").exists()
