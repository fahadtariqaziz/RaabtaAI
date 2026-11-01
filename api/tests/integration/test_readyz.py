"""Needs docker compose postgres+redis (run via scripts/verify/p0_s3.sh)."""

import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


def test_readyz_ok_against_compose_services() -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        database_url=os.environ["IT_DATABASE_URL"],
        redis_url=os.environ["IT_REDIS_URL"],
        jwt_secret="test-secret",  # noqa: S106
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/readyz")
    assert response.status_code == 200, response.json()
    assert response.json()["checks"] == {"database": "ok", "redis": "ok"}
