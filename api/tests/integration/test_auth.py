"""Auth: login, refresh rotation + reuse detection, logout, lockout, role gating (step 1.2)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import create_access_token
from tests.support import PASSWORD, Factory, auth_headers, login

pytestmark = pytest.mark.integration


def test_login_returns_access_token_cookie_and_memberships(
    client: TestClient, factory: Factory
) -> None:
    t = factory.tenant()
    r = client.post(
        "/api/v1/auth/login", json={"email": t.emails["admin"].upper(), "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 900
    assert [m["role"] for m in body["memberships"]] == ["admin"]
    assert body["memberships"][0]["institution_id"] == str(t.id)
    cookie = r.headers["set-cookie"]
    assert "raabta_rt=" in cookie and "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie
    assert "samesite=strict" in cookie.lower()
    assert "password" not in r.text


def test_login_rejects_wrong_password_and_unknown_email(
    client: TestClient, factory: Factory
) -> None:
    t = factory.tenant(("owner",))
    bad = client.post("/api/v1/auth/login", json={"email": t.emails["owner"], "password": "x"})
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "nobody@raabta-test.pk", "password": PASSWORD}
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()  # no user enumeration


def test_me_requires_valid_token(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    t = factory.tenant(("staff",))
    assert client.get("/api/v1/auth/me").status_code == 401
    token = login(client, t.emails["staff"])["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["user"]["email"] == t.emails["staff"]

    expired = create_access_token(
        t.users["staff"],
        secret=it_settings.jwt_secret.get_secret_value(),
        ttl=timedelta(seconds=-1),
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code
        == 401
    )
    forged = create_access_token(t.users["staff"], secret="x" * 40, ttl=timedelta(minutes=5))
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code
        == 401
    )


def test_refresh_rotates_and_reuse_revokes_family(client: TestClient, factory: Factory) -> None:
    t = factory.tenant(("owner",))
    login(client, t.emails["owner"])
    first = client.cookies.get("raabta_rt")
    assert first

    r1 = client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200, r1.text
    second = client.cookies.get("raabta_rt")
    assert second and second != first

    # Replaying the consumed token → 401 and the whole family (incl. `second`) is revoked.
    client.cookies.clear()
    client.cookies.set("raabta_rt", first, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
    client.cookies.clear()
    client.cookies.set("raabta_rt", second, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_refresh(client: TestClient, factory: Factory) -> None:
    t = factory.tenant(("owner",))
    login(client, t.emails["owner"])
    token = client.cookies.get("raabta_rt")
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.clear()
    client.cookies.set("raabta_rt", token or "", path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_lockout_after_ten_failures(client: TestClient, factory: Factory) -> None:
    t = factory.tenant(("owner",))
    email = t.emails["owner"]
    for _ in range(10):
        r = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass1"})
        assert r.status_code == 401
    locked = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0


def test_tenant_header_and_membership_checks(client: TestClient, factory: Factory) -> None:
    a, b = factory.tenant(("admin",)), factory.tenant(("admin",))
    token = login(client, a.emails["admin"])["access_token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/members", headers=bearer).status_code == 400
    bad = {**bearer, "X-Institution": "not-a-uuid"}
    assert client.get("/api/v1/members", headers=bad).status_code == 400
    other = {**bearer, "X-Institution": str(b.id)}
    assert client.get("/api/v1/members", headers=other).status_code == 403
    own = {**bearer, "X-Institution": str(a.id)}
    assert client.get("/api/v1/members", headers=own).status_code == 200


def test_role_gating_staff_cannot_invite(client: TestClient, factory: Factory) -> None:
    t = factory.tenant()
    staff = auth_headers(client, t.emails["staff"], t.id)
    body = {"email": "new@raabta-test.pk", "name": "New", "role": "staff"}
    assert client.post("/api/v1/members/invite", json=body, headers=staff).status_code == 403
    assert client.get("/api/v1/members", headers=staff).status_code == 200


def test_disabled_membership_loses_access(client: TestClient, factory: Factory) -> None:
    t = factory.tenant()
    owner = auth_headers(client, t.emails["owner"], t.id)
    staff = auth_headers(client, t.emails["staff"], t.id)
    members = client.get("/api/v1/members", headers=owner).json()
    staff_member = next(m for m in members if m["role"] == "staff")
    r = client.patch(
        f"/api/v1/members/{staff_member['id']}", json={"status": "disabled"}, headers=owner
    )
    assert r.status_code == 200
    assert client.get("/api/v1/members", headers=staff).status_code == 403
