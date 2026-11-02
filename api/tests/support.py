"""Shared DB fixtures for integration/ and isolation/ tests: app wired to the disposable
`raabta_test` DB as the runtime role
(`raabta_app`, RLS enforced) + Redis db 15. Env set by scripts/verify/p1_s*.sh:
  IT_APP_DATABASE_URL  postgresql+asyncpg://raabta_app:raabta_app@localhost:55432/raabta_test
  IT_REDIS_URL         redis://localhost:56379/15
"""

import asyncio
import os
import tempfile
import uuid
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.tenancy import admin_session, tenant_session
from app.db.session import make_sessionmaker
from app.main import create_app
from app.services import provisioning

PASSWORD = "Sab-theek-123"


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def it_settings() -> Settings:
    db, redis = os.environ.get("IT_APP_DATABASE_URL"), os.environ.get("IT_REDIS_URL")
    if not db or not redis:
        pytest.skip("IT_APP_DATABASE_URL / IT_REDIS_URL not set")
    return Settings(
        _env_file=None,
        env="test",
        database_url=db,
        redis_url=redis,
        jwt_secret="test-secret-0123456789abcdef0123456789",  # noqa: S106
        blob_dir=Path(tempfile.mkdtemp(prefix="raabta-blobs-")),
        embedding_provider="fake",
    )


@pytest.fixture
def client(it_settings: Settings) -> Iterator[TestClient]:
    Redis.from_url(it_settings.redis_url).flushdb()
    with TestClient(create_app(it_settings)) as c:
        yield c


async def as_admin[T](settings: Settings, fn: Any) -> T:
    """Run `fn(session)` in an admin-scoped transaction on a throwaway engine."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with admin_session(make_sessionmaker(engine)) as session:
            result: T = await fn(session)
            return result
    finally:
        await engine.dispose()


async def as_tenant[T](settings: Settings, institution_id: uuid.UUID, fn: Any) -> T:
    """Run `fn(session)` in a tenant-scoped transaction (RLS + ORM filter) on a throwaway engine."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with tenant_session(make_sessionmaker(engine), institution_id) as session:
            result: T = await fn(session)
            return result
    finally:
        await engine.dispose()


@dataclass
class Tenant:
    id: uuid.UUID
    slug: str
    users: dict[str, uuid.UUID]  # role -> user id
    emails: dict[str, str]  # role -> email


@dataclass
class Factory:
    settings: Settings

    def tenant(self, roles: tuple[str, ...] = ("owner", "admin", "staff")) -> Tenant:
        return run(self.atenant(roles))

    async def atenant(self, roles: tuple[str, ...] = ("owner", "admin", "staff")) -> Tenant:
        """Async variant for `async def` tests."""
        tag = uuid.uuid4().hex[:8]

        async def make(session: AsyncSession) -> Tenant:
            inst = await provisioning.upsert_institution(
                session, slug=f"t-{tag}", name=f"Test {tag}", type="school", city="Lahore"
            )
            users, emails = {}, {}
            for role in roles:
                email = f"{role}-{tag}@raabta-test.pk"
                user = await provisioning.upsert_user(
                    session, email=email, name=f"{role} {tag}", password=PASSWORD
                )
                await provisioning.upsert_membership(
                    session, institution_id=inst.id, user_id=user.id, role=role
                )
                users[role], emails[role] = user.id, email
            return Tenant(id=inst.id, slug=inst.slug, users=users, emails=emails)

        return await as_admin(self.settings, make)

    def user(self, *, superadmin: bool = False) -> str:
        email = f"user-{uuid.uuid4().hex[:8]}@raabta-test.pk"

        async def make(session: AsyncSession) -> str:
            await provisioning.upsert_user(
                session, email=email, name="U", password=PASSWORD, is_superadmin=superadmin
            )
            return email

        return run(as_admin(self.settings, make))


@pytest.fixture
def factory(it_settings: Settings) -> Factory:
    return Factory(it_settings)


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, Any]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def auth_headers(client: TestClient, email: str, institution_id: uuid.UUID) -> dict[str, str]:
    token = login(client, email)["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Institution": str(institution_id)}


async def ingest(
    settings: Settings, institution_id: uuid.UUID, document_id: uuid.UUID, **kw: Any
) -> str:
    """Run the KB pipeline in-process (what the arq job does) on a throwaway engine."""
    from app.kb.blobstore import make_blobstore
    from app.kb.embeddings import make_provider
    from app.kb.ingest import IngestDeps, ingest_document

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        deps = IngestDeps(
            sessionmaker=make_sessionmaker(engine),
            blobstore=make_blobstore(settings),
            settings=kw.pop("override_settings", settings),
            provider=make_provider(settings),
            llm=kw.pop("llm", None),
        )
        return await ingest_document(deps, institution_id, document_id)
    finally:
        await engine.dispose()


def upload(
    client: TestClient,
    headers: dict[str, str],
    path_or_bytes: Path | bytes,
    filename: str | None = None,
    title: str | None = None,
) -> Any:
    data = path_or_bytes.read_bytes() if isinstance(path_or_bytes, Path) else path_or_bytes
    name = filename or (path_or_bytes.name if isinstance(path_or_bytes, Path) else "upload.bin")
    form = {"title": title} if title else None
    return client.post(
        "/api/v1/kb/documents", headers=headers, files={"file": (name, data)}, data=form
    )
