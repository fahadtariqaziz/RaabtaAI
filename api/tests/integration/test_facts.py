"""Step 2.6 — facts: deterministic XLSX path (exact PKR), approve/edit/reject + facts_version +
audit, supersede on re-upload, Opus extractor in the pipeline via replayed cassette."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.kb.facts_extractor import FactsBatch, XKeyDate, XProgram
from app.llm.claude import ClaudeClient, ParseResult
from app.models.conversations import LlmRun
from app.models.core import Institution
from app.seeds.schema import SEEDS_DIR, load_seed
from tests.support import Factory, Tenant, as_admin, as_tenant, auth_headers, ingest, run, upload

pytestmark = pytest.mark.integration
ABC = SEEDS_DIR / "abc_grammar_school"
URL = "/api/v1/kb/facts"


def _facts_version(settings: Settings, inst: uuid.UUID) -> int:
    async def get(session: AsyncSession) -> int:
        value = await session.scalar(
            select(Institution.facts_version).where(Institution.id == inst)
        )
        return int(value or 0)

    return run(as_admin(settings, get))


def _ingest_fees(client: TestClient, settings: Settings, t: Tenant) -> dict[str, Any]:
    h = auth_headers(client, t.emails["admin"], t.id)
    doc: dict[str, Any] = upload(
        client, h, ABC / "docs" / "fee_structure.xlsx", title="Fees"
    ).json()
    assert run(ingest(settings, t.id, uuid.UUID(doc["id"]))) == "ready"
    return doc


def test_xlsx_facts_match_seed_exactly_and_approval_flow(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    doc = _ingest_fees(client, it_settings, t)
    pending = client.get(f"{URL}/fee_items?status=pending", headers=h).json()
    seed = load_seed(ABC)
    assert [
        (
            f["fields"]["class_name"],
            f["fields"]["head"],
            f["fields"]["amount_pkr"],
            f["fields"]["frequency"],
        )
        for f in pending
    ] == [(i.class_name, i.head, i.amount_pkr, i.frequency) for i in seed.facts.fee_items]
    first = pending[0]
    assert first["origin"] == "table" and first["academic_year"] == "2026-27"
    assert first["source"]["document_id"] == doc["id"] and first["source"]["page"] == 1
    assert first["source"]["title"] == "Fees"
    routes = client.get(f"{URL}/transport_routes", headers=h).json()
    assert [r["fields"]["monthly_pkr"] for r in routes] == [8500, 7000, 6000, 6500]
    assert all(r["source"]["page"] == 2 for r in routes)

    v0 = _facts_version(it_settings, t.id)
    staff = auth_headers(client, t.emails["staff"], t.id)
    ids = [f["id"] for f in pending]
    body = {"ids": ids, "status": "approved"}
    assert client.patch(f"{URL}/fee_items", json=body, headers=staff).status_code == 403
    r = client.patch(f"{URL}/fee_items", json=body, headers=h)
    assert r.json() == {"updated": 16}
    assert _facts_version(it_settings, t.id) == v0 + 1
    assert client.patch(f"{URL}/fee_items", json=body, headers=h).json() == {"updated": 0}
    assert _facts_version(it_settings, t.id) == v0 + 1  # no-op doesn't bump

    # edit an approved amount → served data changed → bump + audit before/after
    r = client.patch(f"{URL}/fee_items/{ids[3]}", json={"fields": {"amount_pkr": 9900}}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["fields"]["amount_pkr"] == 9900 and r.json()["status"] == "approved"
    assert _facts_version(it_settings, t.id) == v0 + 2
    audit = client.get("/api/v1/audit-log?entity=fee_items", headers=h).json()
    edit = next(a for a in audit if a["action"] == "kb.fact.edit")
    assert (edit["before"]["amount_pkr"], edit["after"]["amount_pkr"]) == (9500, 9900)

    bad = [
        {"fields": {"amount_pkr": -1}},
        {"fields": {"colour": "red"}},
        {"fields": {"frequency": "weekly"}},
    ]
    for payload in bad:
        assert client.patch(f"{URL}/fee_items/{ids[3]}", json=payload, headers=h).status_code == 422
    r = client.patch(f"{URL}/fee_items/{ids[4]}", json={"status": "rejected"}, headers=h)
    assert r.json()["status"] == "rejected" and r.json()["approved_at"] is None
    assert (
        client.patch(
            f"{URL}/fee_items/{uuid.uuid4()}", json={"status": "approved"}, headers=h
        ).status_code
        == 404
    )
    assert client.get(f"{URL}/not_a_kind", headers=h).status_code == 422


def test_reupload_supersedes_old_approved_facts(
    client: TestClient, factory: Factory, it_settings: Settings, tmp_path: Path
) -> None:
    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    _ingest_fees(client, it_settings, t)
    ids = [f["id"] for f in client.get(f"{URL}/fee_items", headers=h).json()]
    client.patch(f"{URL}/fee_items", json={"ids": ids, "status": "approved"}, headers=h)
    v1 = _facts_version(it_settings, t.id)

    wb = load_workbook(ABC / "docs" / "fee_structure.xlsx")
    ws = wb["Fee structure"]
    ws["C3"] = 26000  # first data row after title+header: admission fee 25,000 → 26,000
    new = tmp_path / "fees-2027.xlsx"
    wb.save(new)
    doc2 = upload(client, h, new, title="Fees").json()
    assert doc2["version"] == 2
    assert run(ingest(it_settings, t.id, uuid.UUID(doc2["id"]))) == "ready"
    rows = client.get(f"{URL}/fee_items", headers=h).json()
    assert {r["status"] for r in rows if r["source"]["document_id"] != doc2["id"]} == {"superseded"}
    fresh = [r for r in rows if r["source"]["document_id"] == doc2["id"]]
    assert {r["status"] for r in fresh} == {"pending"}
    assert fresh[0]["fields"]["amount_pkr"] == 26000
    assert _facts_version(it_settings, t.id) == v1 + 1
    old_id = next(r["id"] for r in rows if r["status"] == "superseded")
    r = client.patch(f"{URL}/fee_items/{old_id}", json={"status": "approved"}, headers=h)
    assert r.status_code == 409


def test_llm_extractor_in_pipeline_from_cassette(
    client: TestClient,
    factory: Factory,
    it_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = factory.tenant()
    h = auth_headers(client, t.emails["admin"], t.id)
    lits = SEEDS_DIR / "lits_university" / "docs" / "prospectus.docx"
    doc = upload(client, h, lits, title="LITS guide").json()
    canned = FactsBatch(
        academic_year="Fall 2027",
        fee_items=[],
        programs=[
            XProgram(
                name="BS Computer Science",
                level="undergraduate",
                duration="4 years",
                eligibility="FSc 50% + entry test",
                deadline=None,
                seats=None,
                page=1,
                quote="BS Computer Science PKR 145,000",
            )
        ],
        key_dates=[
            XKeyDate(
                event="Last date to apply (Fall 2027)",
                date="2027-07-15",
                end_date=None,
                notes=None,
                page=1,
                quote="15 July 2027",
            )
        ],
        scholarships=[],
        transport_routes=[],
    )

    async def fake_live(self: ClaudeClient, node: str, *args: Any) -> ParseResult[FactsBatch]:
        return ParseResult(
            output=canned,
            model="claude-opus-5-5",
            effort="high",
            stop_reason="end_turn",
            input_tokens=2000,
            output_tokens=400,
        )

    llm_settings = it_settings.model_copy(update={"kb_facts_llm": True})
    # 1) record (stubbed network) → cassette; 2) a fresh document replays it with no network.
    monkeypatch.setattr(ClaudeClient, "_live", fake_live)
    recorder = ClaudeClient("k", mode="record", cassette_dir=tmp_path)
    assert (
        run(
            ingest(
                it_settings,
                t.id,
                uuid.UUID(doc["id"]),
                llm=recorder,
                override_settings=llm_settings,
            )
        )
        == "ready"
    )
    monkeypatch.undo()
    t2 = factory.tenant()
    h2 = auth_headers(client, t2.emails["admin"], t2.id)
    doc2 = upload(client, h2, lits, title="LITS guide").json()
    replayer = ClaudeClient(None, mode="replay", cassette_dir=tmp_path)
    assert (
        run(
            ingest(
                it_settings,
                t2.id,
                uuid.UUID(doc2["id"]),
                llm=replayer,
                override_settings=llm_settings,
            )
        )
        == "ready"
    )

    programs = client.get(f"{URL}/programs", headers=h2).json()
    assert [(p["fields"]["name"], p["status"], p["origin"]) for p in programs] == [
        ("BS Computer Science", "pending", "llm")
    ]
    assert programs[0]["source"]["page"] == 1 and programs[0]["source"]["title"] == "LITS guide"
    dates = client.get(f"{URL}/key_dates", headers=h2).json()
    assert dates[0]["fields"]["date"] == "2027-07-15"

    async def runs(session: AsyncSession) -> list[tuple[str, int]]:
        rows = await session.execute(select(LlmRun.node, LlmRun.input_tokens))
        return [(r[0], r[1]) for r in rows.all()]

    assert run(as_tenant(it_settings, t.id, runs)) == [("facts_extractor", 2000)]
