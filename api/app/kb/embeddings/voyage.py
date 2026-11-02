"""Voyage AI embeddings (`voyage-3.5`, 1024-d) — Anthropic's documented embedding partner.
REST: POST https://api.voyageai.com/v1/embeddings. Batches ≤ 128 texts; retries 429/5xx."""

import asyncio
import math
import random

import httpx

from app.kb.embeddings.base import EmbeddingError, InputType
from app.models.kb import EMBEDDING_DIM

URL = "https://api.voyageai.com/v1/embeddings"
BATCH = 128
RETRIES = 4


class VoyageProvider:
    dim = EMBEDDING_DIM

    def __init__(
        self,
        api_key: str,
        model: str = "voyage-3.5",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests: httpx.MockTransport
    ) -> None:
        self.name = model
        self._transport = transport
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout
        self.total_tokens = 0  # usage, for cost reporting (bake-off)
        self.backoff = 1.0  # tests set 0

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=self._headers, transport=self._transport
        ) as client:
            for start in range(0, len(texts), BATCH):
                out.extend(await self._batch(client, texts[start : start + BATCH], input_type))
        return out

    async def _batch(
        self, client: httpx.AsyncClient, texts: list[str], input_type: InputType
    ) -> list[list[float]]:
        body = {
            "input": texts,
            "model": self.name,
            "input_type": input_type,
            "output_dimension": self.dim,
        }
        for attempt in range(RETRIES + 1):
            try:
                resp = await client.post(URL, json=body)
            except httpx.TransportError as exc:
                if attempt == RETRIES:
                    raise EmbeddingError(f"voyage connection error: {exc}") from None
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    self.total_tokens += int(data.get("usage", {}).get("total_tokens", 0))
                    rows = sorted(data["data"], key=lambda r: r["index"])
                    return [_unit(r["embedding"]) for r in rows]
                if resp.status_code != 429 and resp.status_code < 500:
                    raise EmbeddingError(f"voyage HTTP {resp.status_code}: {resp.text[:200]}")
                if attempt == RETRIES:
                    raise EmbeddingError(f"voyage HTTP {resp.status_code} after retries")
            await asyncio.sleep(min(2**attempt + random.random(), 20) * self.backoff)  # noqa: S311
        raise EmbeddingError("unreachable")


def _unit(vec: list[float]) -> list[float]:
    length = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / length for v in vec]
