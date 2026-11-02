"""Step 2.7 — playground: answer-less retrieval view (chunks + citations + approved facts)."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.seeds.schema import SEEDS_DIR
from tests.support import Factory, auth_headers, ingest, run, upload

pytestmark = pytest.mark.integration


def test_playground_returns_cited_chunks_and_approved_facts(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    t = factory.tenant()
    admin = auth_headers(client, t.emails["admin"], t.id)
    doc = upload(
        client,
        admin,
        SEEDS_DIR / "abc_grammar_school" / "docs" / "fee_structure.xlsx",
        title="ABC fee structure",
    ).json()
    run(ingest(it_settings, t.id, uuid.UUID(doc["id"])))
    staff = auth_headers(client, t.emails["staff"], t.id)
    body = {"query": "class 5 ki monthly fees kitni hai", "top_k": 3}

    r = client.post("/api/v1/kb/playground", json=body, headers=staff)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["facts"] == []  # nothing approved yet → no facts served
    top = out["chunks"][0]
    assert "Class: Class 5 | Fee head: Tuition fee" in top["text"]
    cit = top["citation"]
    assert (cit["document_id"], cit["title"], cit["page"], cit["chunk_id"]) == (
        doc["id"],
        "ABC fee structure",
        1,
        top["chunk_id"],
    )
    assert cit["quote"] and len(cit["quote"]) <= 241
    assert 0 < out["packed_tokens"] <= 2000

    ids = [f["id"] for f in client.get("/api/v1/kb/facts/fee_items", headers=admin).json()]
    client.patch(
        "/api/v1/kb/facts/fee_items", json={"ids": ids, "status": "approved"}, headers=admin
    )
    out = client.post("/api/v1/kb/playground", json=body, headers=staff).json()
    facts = [f["fields"] for f in out["facts"] if f["kind"] == "fee_items"]
    assert facts and all(f["head"] for f in facts)
    assert (facts[0]["class_name"], facts[0]["amount_pkr"]) == ("Class 5", 12500)
    assert all(f["source"]["title"] == "ABC fee structure" for f in out["facts"])
    # read-only POST: no audit row
    actions = {a["action"] for a in client.get("/api/v1/audit-log", headers=admin).json()}
    assert not any("playground" in a for a in actions)
    bad = client.post("/api/v1/kb/playground", json={"query": ""}, headers=staff)
    assert bad.status_code == 422
