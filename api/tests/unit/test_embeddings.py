"""Step 2.4 — embedding providers (fake offline; Voyage/bge-m3 over mocked HTTP)."""

import json
import math

import httpx
import pytest

from app.core.config import Settings
from app.kb.embeddings import EmbeddingError, make_provider
from app.kb.embeddings.fake import FakeProvider
from app.kb.embeddings.voyage import VoyageProvider
from app.models.kb import EMBEDDING_DIM


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_fake_is_deterministic_normalized_and_similarity_aware() -> None:
    p = FakeProvider()
    a, a2, b, c = await p.embed(
        [
            "Monthly tuition fee for Class 5",
            "monthly tuition FEES for class 5",
            "Class 5 tuition fee per month",
            "Uniform for girls: white shirt",
        ],
        "document",
    )
    assert len(a) == EMBEDDING_DIM
    assert math.isclose(sum(v * v for v in a), 1.0, rel_tol=1e-9)
    assert a == (await p.embed(["Monthly tuition fee for Class 5"], "query"))[0]
    assert _cos(a, a2) > 0.95  # normalization folds case/spelling
    assert _cos(a, b) > _cos(a, c)


def _settings(**kw: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://x@h/d",
        redis_url="redis://h",
        jwt_secret="x" * 40,
        **kw,  # type: ignore[arg-type]
    )


def test_factory() -> None:
    assert make_provider(_settings()).name == "fake-hash-v1"
    with pytest.raises(Exception, match="VOYAGE_API_KEY"):
        make_provider(_settings(embedding_provider="voyage"))
    with pytest.raises(EmbeddingError, match="BGE_M3_URL"):
        make_provider(_settings(embedding_provider="bge_m3"))
    assert make_provider(_settings(embedding_provider="voyage", voyage_api_key="k")).name == (
        "voyage-3.5"
    )


async def test_voyage_request_shape_order_and_retry() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        assert request.headers["authorization"] == "Bearer key"
        if len(calls) == 1:
            return httpx.Response(429, json={"detail": "slow down"})
        data = [
            {"index": i, "embedding": [float(i + 1)] + [0.0] * (EMBEDDING_DIM - 1)}
            for i in range(len(body["input"]))
        ][::-1]  # out of order on purpose
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 7}})

    p = VoyageProvider("key", transport=httpx.MockTransport(handler))
    p.backoff = 0
    vecs = await p.embed(["a", "b"], "query")
    assert calls[-1] == {
        "input": ["a", "b"],
        "model": "voyage-3.5",
        "input_type": "query",
        "output_dimension": EMBEDDING_DIM,
    }
    assert [v[0] for v in vecs] == [1.0, 1.0]  # each normalized; order restored by index
    assert p.total_tokens == 7 and len(calls) == 2


async def test_voyage_client_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"detail": "bad key"})

    p = VoyageProvider("bad", transport=httpx.MockTransport(handler))
    with pytest.raises(EmbeddingError, match="401"):
        await p.embed(["a"], "document")
    assert calls == 1
