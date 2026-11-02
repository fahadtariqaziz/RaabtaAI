"""Demo seeds: idempotent, expected counts, docs on disk with seed numbers, demo logins (1.5)."""

from datetime import date
from typing import Any

import pytest
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.conversations import Contact, Lead, Slot
from app.models.core import Institution, Membership
from app.seeds.loader import SUPERADMIN_EMAIL, seed_institution, seed_superadmin
from app.seeds.schema import load_seed, seed_dirs
from tests.support import as_admin, run

pytestmark = pytest.mark.integration

PASSWORD = "Seed-test-pass-1"
EXPECTED = {  # slug -> (users, contacts, slots)
    "abc-grammar-school": (3, 12, 72),
    "punjab-model-college": (3, 8, 90),
    "lits-university": (3, 10, 8),
}


def seed_all(settings: Settings) -> None:
    async def go(session: AsyncSession) -> None:
        await seed_superadmin(session, PASSWORD)
        for d in seed_dirs():
            await seed_institution(
                session, load_seed(d), d, password=PASSWORD, today=date(2027, 1, 20)
            )

    run(as_admin(settings, go))


def counts(settings: Settings) -> dict[str, tuple[int, int, int]]:
    async def q(session: AsyncSession) -> dict[str, tuple[int, int, int]]:
        out = {}
        for slug in EXPECTED:
            inst = await session.scalar(select(Institution.id).where(Institution.slug == slug))
            vals = []
            for model in (Membership, Contact, Slot):
                n = await session.scalar(
                    select(func.count()).select_from(model).where(model.institution_id == inst)
                )
                vals.append(int(n or 0))
            leads = await session.scalar(
                select(func.count()).select_from(Lead).where(Lead.institution_id == inst)
            )
            assert leads == vals[1]
            out[slug] = (vals[0], vals[1], vals[2])
        return out

    return run(as_admin(settings, q))


@pytest.fixture(scope="module")
def seeded(it_settings: Settings) -> Settings:
    seed_all(it_settings)
    seed_all(it_settings)  # idempotent: second run must not duplicate anything
    return it_settings


def test_seed_is_idempotent_with_expected_counts(seeded: Settings) -> None:
    assert counts(seeded) == EXPECTED


def test_seed_documents_on_disk_match_facts() -> None:
    for d in seed_dirs():
        seed = load_seed(d)
        xlsx, docx = d / "docs" / "fee_structure.xlsx", d / "docs" / "prospectus.docx"
        assert xlsx.is_file()
        assert docx.is_file()
        ws = load_workbook(xlsx, read_only=True)["Fee structure"]
        amounts = [r[2] for r in ws.iter_rows(min_row=3, values_only=True)]
        assert amounts == [f.amount_pkr for f in seed.facts.fee_items]
        text = "\n".join(p.text for p in Document(str(docx)).paragraphs)
        assert seed.prospectus.sections[0].heading in text


def test_spec_values_present() -> None:
    by_slug = {load_seed(d).institution.slug: load_seed(d) for d in seed_dirs()}
    abc = {
        (f.class_name, f.head): f.amount_pkr for f in by_slug["abc-grammar-school"].facts.fee_items
    }
    assert abc[("All classes", "Admission fee")] == 25000
    assert abc[("All classes", "Security deposit")] == 20000
    monthly = [v for (_, head), v in abc.items() if head == "Tuition fee"]
    assert (min(monthly), max(monthly)) == (9500, 16500)
    lits = {f.program: f.amount_pkr for f in by_slug["lits-university"].facts.fee_items}
    assert lits["BS Computer Science"] == 145000
    assert lits["BBA"] == 120000


@pytest.mark.parametrize("role", ["owner", "admin", "staff"])
def test_demo_users_can_log_in(seeded: Settings, client: TestClient, role: str) -> None:
    for d in seed_dirs():
        seed = load_seed(d)
        user = next(u for u in seed.users if u.role == role)
        r = client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        body: dict[str, Any] = r.json()
        assert [(m["institution_slug"], m["role"]) for m in body["memberships"]] == [
            (seed.institution.slug, role)
        ]


def test_superadmin_can_log_in(seeded: Settings, client: TestClient) -> None:
    r = client.post("/api/v1/auth/login", json={"email": SUPERADMIN_EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["user"]["is_superadmin"] is True
