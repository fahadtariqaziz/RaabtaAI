from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_returns_ok_and_request_id_header() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(response.headers["x-request-id"]) == 32


def test_incoming_request_id_is_echoed() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"


def test_readyz_is_503_when_dependencies_unreachable() -> None:
    # conftest points DATABASE_URL/REDIS_URL at port 1 (nothing listening).
    with TestClient(create_app()) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"].startswith("error")
    assert body["checks"]["redis"].startswith("error")
