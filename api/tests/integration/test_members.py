"""Members + invitations + owner rules + audit rows (step 1.2)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.core import AuditLog
from tests.support import PASSWORD, Factory, as_admin, auth_headers, run

pytestmark = pytest.mark.integration


def audit_actions(settings: Settings, institution_id: Any) -> list[str]:
    async def q(session: AsyncSession) -> list[str]:
        rows = await session.scalars(
            select(AuditLog.action)
            .where(AuditLog.institution_id == institution_id)
            .order_by(AuditLog.created_at)
        )
        return list(rows)

    return run(as_admin(settings, q))


def invite(client: TestClient, headers: dict[str, str], email: str, role: str = "staff") -> Any:
    return client.post(
        "/api/v1/members/invite",
        json={"email": email, "name": "Ayesha Khan", "role": role},
        headers=headers,
    )


def test_invite_accept_login_flow(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    t = factory.tenant()
    admin = auth_headers(client, t.emails["admin"], t.id)
    r = invite(client, admin, "Ayesha@Raabta-Test.pk")
    assert r.status_code == 201, r.text
    body = r.json()
    assert (
        body["member"]["status"] == "invited" and body["member"]["email"] == "ayesha@raabta-test.pk"
    )
    token = body["invite_url"].split("#token=")[1]

    assert invite(client, admin, "ayesha@raabta-test.pk").status_code == 409

    weak = client.post(
        "/api/v1/auth/invitations/accept", json={"token": token, "password": "short"}
    )
    assert weak.status_code == 422
    ok = client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": token, "password": "Naya-password-2027"},
    )
    assert ok.status_code == 200, ok.text
    assert [m["institution_id"] for m in ok.json()["memberships"]] == [str(t.id)]
    again = client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": token, "password": "Naya-password-2027"},
    )
    assert again.status_code == 400  # one-time token

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "ayesha@raabta-test.pk", "password": "Naya-password-2027"},
    )
    assert login.status_code == 200
    assert audit_actions(it_settings, t.id) == ["member.invited", "member.invite_accepted"]


def test_existing_user_must_use_own_password_to_accept(
    client: TestClient, factory: Factory
) -> None:
    a, b = factory.tenant(("owner",)), factory.tenant(("owner",))
    r = invite(client, auth_headers(client, b.emails["owner"], b.id), a.emails["owner"], "admin")
    token = r.json()["invite_url"].split("#token=")[1]
    wrong = client.post(
        "/api/v1/auth/invitations/accept", json={"token": token, "password": "Other-pass-999"}
    )
    assert wrong.status_code == 400
    ok = client.post("/api/v1/auth/invitations/accept", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 200
    assert {m["institution_id"] for m in ok.json()["memberships"]} == {str(a.id), str(b.id)}


def test_only_owner_manages_owners_and_last_owner_is_kept(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    t = factory.tenant()
    admin = auth_headers(client, t.emails["admin"], t.id)
    owner = auth_headers(client, t.emails["owner"], t.id)
    assert invite(client, admin, "boss@raabta-test.pk", "owner").status_code == 403

    members = {m["role"]: m for m in client.get("/api/v1/members", headers=owner).json()}
    owner_id, staff_id = members["owner"]["id"], members["staff"]["id"]
    assert client.delete(f"/api/v1/members/{owner_id}", headers=admin).status_code == 403
    assert (
        client.patch(
            f"/api/v1/members/{staff_id}", json={"role": "owner"}, headers=admin
        ).status_code
        == 403
    )
    demote = client.patch(f"/api/v1/members/{owner_id}", json={"role": "admin"}, headers=owner)
    assert demote.status_code == 409  # last active owner

    promote = client.patch(f"/api/v1/members/{staff_id}", json={"role": "admin"}, headers=admin)
    assert promote.status_code == 200 and promote.json()["role"] == "admin"
    assert client.delete(f"/api/v1/members/{staff_id}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/members/{staff_id}", headers=admin).status_code == 404

    actions = audit_actions(it_settings, t.id)
    assert actions == ["member.updated", "member.removed"]  # failed attempts leave no rows


def test_member_ids_from_other_institution_are_not_found(
    client: TestClient, factory: Factory
) -> None:
    a, b = factory.tenant(), factory.tenant()
    a_owner = auth_headers(client, a.emails["owner"], a.id)
    b_owner = auth_headers(client, b.emails["owner"], b.id)
    b_member = client.get("/api/v1/members", headers=b_owner).json()[0]["id"]
    assert (
        client.patch(
            f"/api/v1/members/{b_member}", json={"role": "staff"}, headers=a_owner
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/members/{b_member}", headers=a_owner).status_code == 404
    assert len(client.get("/api/v1/members", headers=a_owner).json()) == 3
