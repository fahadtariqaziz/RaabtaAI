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
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.support import Factory, Tenant, auth_headers, ingest, run

pytestmark = [pytest.mark.isolation, pytest.mark.integration]

PREFIX = "/api/v1"
PUBLIC_ROUTES = {
    ("POST", "/auth/login"): "credentials in body",
    ("POST", "/auth/refresh"): "refresh cookie identifies the user",
    ("POST", "/auth/logout"): "refresh cookie",
    ("POST", "/auth/invitations/accept"): "one-time invite token",
    ("GET", "/auth/me"): "user-scoped (own memberships only), no X-Institution",
}
# Static dict or `fn(world) -> dict` (bodies that must carry the other tenant's ids).
SAMPLE_BODIES: dict[tuple[str, str], Any] = {
    ("POST", "/members/invite"): {"email": "probe@raabta-test.pk", "name": "P", "role": "staff"},
    ("PATCH", "/members/{member_id}"): {"role": "staff"},
    ("POST", "/kb/documents/{document_id}/reindex"): None,
    ("PATCH", "/kb/facts/{kind}"): lambda w: {"ids": [_b_fact_id(w)], "status": "rejected"},
    ("PATCH", "/kb/facts/{kind}/{fact_id}"): {"status": "rejected"},
    ("POST", "/kb/playground"): {"query": "fee"},
}
# Multipart routes: files sent instead of a JSON body.
SAMPLE_FILES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/kb/documents"): {"file": ("probe.csv", b"Class,Fee head,Amount\nX,Probe,1\n")},
}
# Path params that are not object ids (enum-like): not resolved to the other tenant's objects.
NON_ID_PARAMS = {"kind": "fee_items"}
FACT_KINDS = ("programs", "fee_items", "key_dates", "scholarships", "transport_routes")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
B_FEES_CSV = b"Class,Fee head,Amount (PKR),Frequency\nClass 9,Tuition fee,16500,Monthly\n"


@dataclass
class World:
    client: TestClient
    a: Tenant
    b: Tenant
    a_owner: dict[str, str]
    b_owner: dict[str, str]
    settings: Settings
    cache: dict[str, str] = field(default_factory=dict)

    def b_snapshot(self) -> str:
        """Everything B's owner can see through list endpoints (to detect cross-tenant writes)."""
        parts = []
        for method, path in tenant_routes():
            if method == "GET" and "{" not in path:
                r = self.client.get(PREFIX + path, headers=self.b_owner)
                parts.append(r.text)
        for kind in FACT_KINDS:
            parts.append(self.client.get(f"{PREFIX}/kb/facts/{kind}", headers=self.b_owner).text)
        return "\n".join(parts)

    def b_markers(self) -> set[str]:
        members = self.client.get(PREFIX + "/members", headers=self.b_owner).json()
        _b_document_id(self)
        docs = self.client.get(PREFIX + "/kb/documents", headers=self.b_owner).json()
        return (
            {str(self.b.id)}
            | {m["id"] for m in members}
            | set(self.b.emails.values())
            | {d["id"] for d in docs}
            | {"B-secret-fees"}
        )


def _b_member_id(w: World) -> str:
    members = w.client.get(PREFIX + "/members", headers=w.b_owner).json()
    return str(next(m["id"] for m in members if m["role"] == "staff"))


def _const(value: str) -> Callable[[World], str]:
    return lambda _w: value


def _b_document_id(w: World) -> str:
    """B owns one ingested document (chunks + pending fee facts)."""
    if "doc" not in w.cache:
        r = w.client.post(
            PREFIX + "/kb/documents",
            headers=w.b_owner,
            files={"file": ("fees.csv", B_FEES_CSV)},
            data={"title": "B-secret-fees"},
        )
        assert r.status_code == 201, r.text
        w.cache["doc"] = r.json()["id"]
        assert run(ingest(w.settings, w.b.id, uuid.UUID(w.cache["doc"]))) == "ready"
    return w.cache["doc"]


def _b_fact_id(w: World) -> str:
    _b_document_id(w)
    if "fact" not in w.cache:
        facts = w.client.get(PREFIX + "/kb/facts/fee_items", headers=w.b_owner).json()
        w.cache["fact"] = facts[0]["id"]
    return w.cache["fact"]


ID_RESOLVERS: dict[str, Callable[[World], str]] = {
    "member_id": _b_member_id,
    "document_id": _b_document_id,
    "fact_id": _b_fact_id,
    **{name: _const(value) for name, value in NON_ID_PARAMS.items()},
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
            assert (method, path) in SAMPLE_BODIES or (method, path) in SAMPLE_FILES, (
                f"{method} {path}: add a SAMPLE_BODIES (or SAMPLE_FILES) entry"
            )


@pytest.fixture
def world(client: TestClient, factory: Factory, it_settings: Settings) -> World:
    a, b = factory.tenant(), factory.tenant()
    w = World(
        client=client,
        a=a,
        b=b,
        a_owner=auth_headers(client, a.emails["owner"], a.id),
        b_owner=auth_headers(client, b.emails["owner"], b.id),
        settings=it_settings,
    )
    _b_fact_id(w)  # B owns an ingested document + facts before any snapshot is taken
    return w


def _send(w: World, method: str, route: str, url: str, headers: dict[str, str]) -> Any:
    """Request `url` (filled `route`) with the route's sample JSON body or multipart files."""
    if (method, route) in SAMPLE_FILES:
        return w.client.request(method, url, headers=headers, files=SAMPLE_FILES[(method, route)])
    body = SAMPLE_BODIES.get((method, route))
    if callable(body):
        body = body(w)
    return w.client.request(method, url, headers=headers, json=body)


def id_params(path: str) -> list[str]:
    return [p for p in path_params(path) if p not in NON_ID_PARAMS]


def _fill(path: str, values: dict[str, str]) -> str:
    return path.format(**values)


@pytest.mark.parametrize(("method", "path"), tenant_routes())
def test_foreign_institution_header_is_forbidden(world: World, method: str, path: str) -> None:
    """A's owner names B's institution → 403 on every tenant route, nothing written in B."""
    before = world.b_snapshot()
    headers = {**world.a_owner, "X-Institution": str(world.b.id)}
    ids = {p: ID_RESOLVERS[p](world) for p in path_params(path)}
    r = _send(world, method, path, PREFIX + _fill(path, ids), headers)
    assert r.status_code == 403, (method, path, r.status_code, r.text)
    assert world.b_snapshot() == before


@pytest.mark.parametrize(("method", "path"), [rt for rt in tenant_routes() if id_params(rt[1])])
def test_foreign_object_ids_are_not_found(world: World, method: str, path: str) -> None:
    """A's owner, own institution header, but B's object ids in the path → 404, B unchanged."""
    before = world.b_snapshot()
    ids = {p: ID_RESOLVERS[p](world) for p in path_params(path)}
    r = _send(world, method, path, PREFIX + _fill(path, ids), world.a_owner)
    assert r.status_code == 404, (method, path, r.status_code, r.text)
    assert world.b_snapshot() == before


def test_foreign_ids_in_bodies_change_nothing(world: World) -> None:
    """Bulk fact status with B's fact ids from A's institution → nothing updated in B."""
    before = world.b_snapshot()
    body = SAMPLE_BODIES[("PATCH", "/kb/facts/{kind}")](world)
    r = world.client.patch(PREFIX + "/kb/facts/fee_items", json=body, headers=world.a_owner)
    assert r.status_code == 200 and r.json() == {"updated": 0}
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
    world.client.post(PREFIX + "/kb/playground", json={"query": "Probe"}, headers=world.b_owner)
    r = world.client.get(PREFIX + path, headers=world.a_owner)
    assert r.status_code == 200, (path, r.text)
    text = json.dumps(r.json())
    leaked = {m for m in markers if m in text}
    assert not leaked, f"{path} leaked {leaked}"
