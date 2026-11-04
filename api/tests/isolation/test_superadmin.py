"""Step 5.9.3 — superadmin paths: platform routes are superadmin-only; a superadmin has no tenant
access until an (audited) impersonation grant exists, and loses it when the grant is ended."""

import pytest
from fastapi.testclient import TestClient

from tests.isolation.test_endpoints import PREFIX, SUPERADMIN_PREFIX, all_routes
from tests.support import Factory, login

pytestmark = [pytest.mark.isolation, pytest.mark.integration]


def _bearer(client: TestClient, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(client, email)['access_token']}"}


def test_platform_routes_are_superadmin_only(client: TestClient, factory: Factory) -> None:
    t = factory.tenant()
    owner = _bearer(client, t.emails["owner"])
    routes = [r for r in all_routes() if r[1].startswith(SUPERADMIN_PREFIX)]
    assert len(routes) >= 6
    for method, path in routes:
        url = PREFIX + path.replace("{institution_id}", str(t.id))
        body: dict[str, str] | None = {} if method in ("POST", "PATCH") else None
        r = client.request(method, url, headers=owner, json=body)
        assert r.status_code == 403, (method, path, r.status_code)


def test_impersonation_is_explicit_audited_and_revocable(
    client: TestClient, factory: Factory
) -> None:
    t = factory.tenant()
    sa = _bearer(client, factory.user(superadmin=True))
    tenant_h = {**sa, "X-Institution": str(t.id)}
    assert client.get(PREFIX + "/leads", headers=tenant_h).status_code == 403

    r = client.post(f"{PREFIX}/superadmin/impersonate/{t.id}", headers=sa)
    assert r.status_code == 200 and r.json()["institution_id"] == str(t.id)
    assert client.get(PREFIX + "/leads", headers=tenant_h).status_code == 200

    owner = {**_bearer(client, t.emails["owner"]), "X-Institution": str(t.id)}
    actions = [a["action"] for a in client.get(PREFIX + "/audit-log", headers=owner).json()]
    assert "superadmin.impersonate" in actions  # visible to the tenant's own admins

    other = factory.tenant()  # the grant is per institution
    other_h = {**sa, "X-Institution": str(other.id)}
    assert client.get(PREFIX + "/leads", headers=other_h).status_code == 403

    assert client.delete(f"{PREFIX}/superadmin/impersonate/{t.id}", headers=sa).status_code == 204
    assert client.get(PREFIX + "/leads", headers=tenant_h).status_code == 403
