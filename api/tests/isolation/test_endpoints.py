"""Cross-tenant attempts through every API route (step 1.7, PLAN §18/§20).

Routes are auto-discovered from the app. Each `/api/v1` route must be either
- in PUBLIC_ROUTES (no tenant context; justified), or
- a tenant route: then, for user A,
    1. `X-Institution: B` → 403 (no membership), and
    2. path ids that belong to B (resolved via ID_RESOLVERS) → 404 and B's data unchanged, and
    3. GET responses never contain B's identifiers (zero leakage).
Adding a route with a new path parameter or a mutating route without a sample body fails
`test_every_route_is_classified` until this file is taught about it.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.support import Factory, Tenant, auth_headers

pytestmark = [pytest.mark.isolation, pytest.mark.integration]

PREFIX = "/api/v1"
PUBLIC_ROUTES = {
    ("POST", "/auth/login"): "credentials in body",
    ("POST", "/auth/refresh"): "refresh cookie identifies the user",
    ("POST", "/auth/logout"): "refresh cookie",
    ("POST", "/auth/invitations/accept"): "one-time invite token",
    ("GET", "/auth/me"): "user-scoped (own memberships only), no X-Institution",
}
SAMPLE_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/members/invite"): {"email": "probe@raabta-test.pk", "name": "P", "role": "staff"},
    ("PATCH", "/members/{member_id}"): {"role": "staff"},
}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class World:
    client: TestClient
    a: Tenant
    b: Tenant
    a_owner: dict[str, str]
    b_owner: dict[str, str]

    def b_snapshot(self) -> str:
        """Everything B's owner can see through list endpoints (to detect cross-tenant writes)."""
        parts = []
        for method, path in tenant_routes():
            if method == "GET" and "{" not in path:
                r = self.client.get(PREFIX + path, headers=self.b_owner)
                parts.append(r.text)
        return "\n".join(parts)

    def b_markers(self) -> set[str]:
        members = self.client.get(PREFIX + "/members", headers=self.b_owner).json()
        return {str(self.b.id)} | {m["id"] for m in members} | set(self.b.emails.values())


def _b_member_id(w: World) -> str:
    members = w.client.get(PREFIX + "/members", headers=w.b_owner).json()
    return str(next(m["id"] for m in members if m["role"] == "staff"))


ID_RESOLVERS: dict[str, Callable[[World], str]] = {
    "member_id": _b_member_id,
}


def all_routes() -> list[tuple[str, str]]:
    """(METHOD, path) for every /api/v1 operation, from the OpenAPI schema (covers nested and
    lazily-included routers)."""
    settings = Settings(
        _env_file=None,
        env="test",
        database_url="postgresql+asyncpg://x@h/d",
        redis_url="redis://h",
        jwt_secret="x" * 40,
    )
    paths: dict[str, dict[str, Any]] = create_app(settings).openapi()["paths"]
    return sorted(
        (method.upper(), path.removeprefix(PREFIX))
        for path, ops in paths.items()
        if path.startswith(PREFIX)
        for method in ops
    )


def tenant_routes() -> list[tuple[str, str]]:
    return [rt for rt in all_routes() if rt not in PUBLIC_ROUTES]


def path_params(path: str) -> list[str]:
    return re.findall(r"{(\w+)}", path)


def test_every_route_is_classified() -> None:
    routes = all_routes()
    assert routes, "no routes discovered"
    stale = set(PUBLIC_ROUTES) - set(routes)
    assert not stale, f"PUBLIC_ROUTES lists routes that no longer exist: {stale}"
    for method, path in tenant_routes():
        unknown = [p for p in path_params(path) if p not in ID_RESOLVERS]
        assert not unknown, f"{method} {path}: add an ID_RESOLVERS entry for {unknown}"
        if method in {"POST", "PUT", "PATCH"}:
            assert (method, path) in SAMPLE_BODIES, f"{method} {path}: add a SAMPLE_BODIES entry"


@pytest.fixture
def world(client: TestClient, factory: Factory) -> World:
    a, b = factory.tenant(), factory.tenant()
    return World(
        client=client,
        a=a,
        b=b,
        a_owner=auth_headers(client, a.emails["owner"], a.id),
        b_owner=auth_headers(client, b.emails["owner"], b.id),
    )


def _call(w: World, method: str, path: str, headers: dict[str, str]) -> Any:
    body = SAMPLE_BODIES.get((method, path.split("?")[0]))
    return w.client.request(method, PREFIX + path, headers=headers, json=body)


def _fill(path: str, values: dict[str, str]) -> str:
    return path.format(**values)


@pytest.mark.parametrize(("method", "path"), tenant_routes())
def test_foreign_institution_header_is_forbidden(world: World, method: str, path: str) -> None:
    """A's owner names B's institution → 403 on every tenant route, nothing written in B."""
    before = world.b_snapshot()
    headers = {**world.a_owner, "X-Institution": str(world.b.id)}
    ids = {p: ID_RESOLVERS[p](world) for p in path_params(path)}
    r = world.client.request(
        method,
        PREFIX + _fill(path, ids),
        headers=headers,
        json=SAMPLE_BODIES.get((method, path)),
    )
    assert r.status_code == 403, (method, path, r.status_code, r.text)
    assert world.b_snapshot() == before


@pytest.mark.parametrize(("method", "path"), [rt for rt in tenant_routes() if path_params(rt[1])])
def test_foreign_object_ids_are_not_found(world: World, method: str, path: str) -> None:
    """A's owner, own institution header, but B's object ids in the path → 404, B unchanged."""
    before = world.b_snapshot()
    ids = {p: ID_RESOLVERS[p](world) for p in path_params(path)}
    r = world.client.request(
        method,
        PREFIX + _fill(path, ids),
        headers=world.a_owner,
        json=SAMPLE_BODIES.get((method, path)),
    )
    assert r.status_code == 404, (method, path, r.status_code, r.text)
    assert world.b_snapshot() == before


@pytest.mark.parametrize(
    ("method", "path"), [rt for rt in tenant_routes() if rt[0] == "GET" and not path_params(rt[1])]
)
def test_list_endpoints_leak_nothing_from_other_tenant(
    world: World, method: str, path: str
) -> None:
    # give B some activity so there is something to leak
    world.client.post(
        PREFIX + "/members/invite",
        json={"email": "b-secret@raabta-test.pk", "name": "B Secret", "role": "staff"},
        headers=world.b_owner,
    )
    markers = world.b_markers() | {"b-secret@raabta-test.pk"}
    r = world.client.get(PREFIX + path, headers=world.a_owner)
    assert r.status_code == 200, (path, r.text)
    text = json.dumps(r.json())
    leaked = {m for m in markers if m in text}
    assert not leaked, f"{path} leaked {leaked}"
