"""Audit log: explicit rows, generic mutation rows, listing endpoint, scoping (step 1.6)."""

from collections.abc import Iterator

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from app.api.deps import AdminCtx, audit_mutations
from app.core.config import Settings
from app.main import create_app
from tests.support import Factory, auth_headers

pytestmark = pytest.mark.integration


@pytest.fixture
def app_client(it_settings: Settings) -> Iterator[TestClient]:
    """App with an extra tenant router that never calls audit() explicitly."""
    app = create_app(it_settings)
    probe = APIRouter(prefix="/api/v1/_probe", dependencies=[audit_mutations])

    @probe.post("/things/{thing_id}")
    async def touch(thing_id: str, _: AdminCtx) -> dict[str, str]:
        return {"ok": thing_id}

    @probe.post("/fail")
    async def fail(_: AdminCtx) -> None:
        raise HTTPException(400, "nope")

    app.include_router(probe)
    with TestClient(app) as c:
        yield c


def test_member_change_is_listed_with_before_after(client: TestClient, factory: Factory) -> None:
    t = factory.tenant()
    owner = auth_headers(client, t.emails["owner"], t.id)
    staff_id = next(
        m["id"] for m in client.get("/api/v1/members", headers=owner).json() if m["role"] == "staff"
    )
    client.patch(f"/api/v1/members/{staff_id}", json={"role": "admin"}, headers=owner)
    client.post(
        "/api/v1/members/invite",
        json={"email": "new-teacher@raabta-test.pk", "name": "N", "role": "staff"},
        headers=owner,
    )
    rows = client.get("/api/v1/audit-log", headers=owner).json()
    assert [r["action"] for r in rows] == ["member.invited", "member.updated"]  # newest first
    updated = rows[1]
    assert updated["before"] == {"role": "staff", "status": "active"}
    assert updated["after"] == {"role": "admin", "status": "active"}
    assert updated["actor_user_id"] == str(t.users["owner"])
    assert "token" not in str(rows[0]["after"])
    only = client.get("/api/v1/audit-log?action=member.updated", headers=owner).json()
    assert len(only) == 1


def test_audit_log_is_admin_only_and_tenant_scoped(client: TestClient, factory: Factory) -> None:
    a, b = factory.tenant(), factory.tenant()
    a_owner = auth_headers(client, a.emails["owner"], a.id)
    b_owner = auth_headers(client, b.emails["owner"], b.id)
    staff_id = next(
        m["id"]
        for m in client.get("/api/v1/members", headers=a_owner).json()
        if m["role"] == "staff"
    )
    client.patch(f"/api/v1/members/{staff_id}", json={"status": "disabled"}, headers=a_owner)
    assert client.get("/api/v1/audit-log", headers=b_owner).json() == []
    staff = auth_headers(client, b.emails["staff"], b.id)
    assert client.get("/api/v1/audit-log", headers=staff).status_code == 403


def test_generic_row_for_unaudited_mutation_and_none_on_failure(
    app_client: TestClient, factory: Factory
) -> None:
    t = factory.tenant()
    admin = auth_headers(app_client, t.emails["admin"], t.id)
    assert app_client.post("/api/v1/_probe/things/42", headers=admin).status_code == 200
    assert app_client.post("/api/v1/_probe/fail", headers=admin).status_code == 400
    rows = app_client.get("/api/v1/audit-log", headers=admin).json()
    assert [r["action"] for r in rows] == ["POST /api/v1/_probe/things/{thing_id}"]
    assert rows[0]["after"] == {"path_params": {"thing_id": "42"}}
    assert rows[0]["entity"] == "http"
