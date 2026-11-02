"""`EmbeddingProvider` interface + factory. Every provider returns L2-normalized vectors of
`EMBEDDING_DIM` (the `chunks.embedding` column); switching provider = re-embed all chunks
(`app.kb.ingest.reembed_all`)."""

from typing import Literal, Protocol

from app.core.config import Settings
from app.models.kb import EMBEDDING_DIM

InputType = Literal["document", "query"]


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    name: str  # stored in chunks.embedding_model, e.g. "voyage-3.5"
    dim: int

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]: ...


def make_provider(settings: Settings, override: str | None = None) -> EmbeddingProvider:
    kind = override or settings.embedding_provider
    if kind == "fake":
        from app.kb.embeddings.fake import FakeProvider

        return FakeProvider()
    if kind == "voyage":
        from app.kb.embeddings.voyage import VoyageProvider

        return VoyageProvider(settings.require("voyage_api_key"), model=settings.embedding_model)
    if kind == "bge_m3":
        from app.kb.embeddings.bge import BGEM3Provider

        if not settings.bge_m3_url:
            raise EmbeddingError("BGE_M3_URL is not set (TEI endpoint serving BAAI/bge-m3)")
        return BGEM3Provider(settings.bge_m3_url)
    raise EmbeddingError(f"unknown embedding provider {kind!r}")


__all__ = ["EMBEDDING_DIM", "EmbeddingError", "EmbeddingProvider", "InputType", "make_provider"]
