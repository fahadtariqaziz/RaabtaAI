"""Self-hosted `BAAI/bge-m3` (1024-d) behind a Hugging Face Text-Embeddings-Inference endpoint:
POST {url}/embed {"inputs": [...], "normalize": true} → [[...], ...]. bge-m3 needs no query/document
prefix, so `input_type` is ignored."""

import httpx

from app.kb.embeddings.base import EmbeddingError, InputType
from app.models.kb import EMBEDDING_DIM

BATCH = 32


class BGEM3Provider:
    name = "bge-m3"
    dim = EMBEDDING_DIM

    def __init__(self, url: str, timeout: float = 120.0) -> None:
        self._url = url.rstrip("/") + "/embed"
        self._timeout = timeout

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for start in range(0, len(texts), BATCH):
                batch = texts[start : start + BATCH]
                try:
                    resp = await client.post(self._url, json={"inputs": batch, "normalize": True})
                except httpx.TransportError as exc:
                    raise EmbeddingError(f"bge-m3 endpoint unreachable: {exc}") from None
                if resp.status_code != 200:
                    raise EmbeddingError(f"bge-m3 HTTP {resp.status_code}: {resp.text[:200]}")
                vectors: list[list[float]] = resp.json()
                if vectors and len(vectors[0]) != self.dim:
                    raise EmbeddingError(f"bge-m3 returned dim {len(vectors[0])}, need {self.dim}")
                out.extend(vectors)
        return out
