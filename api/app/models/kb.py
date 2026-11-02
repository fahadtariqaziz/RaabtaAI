"""Knowledge base (PLAN §13): documents (versioned uploads) and chunks (hybrid-search units).
Both tenant-scoped (TenantMixin + RLS in migration 0004)."""

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampsMixin, UUIDPkMixin, enum_check
from app.models.enums import CHUNK_LANGS, DOCUMENT_KINDS, DOCUMENT_STATUSES

# Embedding dimension (voyage-3.5 and bge-m3 are both 1024-d). Changing it = new migration +
# full re-index (PLAN §4 Embeddings).
EMBEDDING_DIM = 1024


class Document(UUIDPkMixin, TenantMixin, TimestampsMixin, Base):
    """One uploaded file version. A re-upload with the same title is version+1 and supersedes the
    previous version once it reaches `ready` (old chunks removed in the same transaction)."""

    __tablename__ = "documents"
    __table_args__ = (
        enum_check("kind", DOCUMENT_KINDS),
        enum_check("status", DOCUMENT_STATUSES),
        Index(None, "institution_id", "created_at"),
        Index(None, "institution_id", "checksum"),
        Index(None, "institution_id", "title"),
    )

    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))  # BlobStore key, never a public URL
    mime: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum: Mapped[str] = mapped_column(String(64))  # sha256 hex
    pages: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), server_default="uploaded")
    error: Mapped[str | None] = mapped_column(Text)
    # Pipeline bookkeeping: failed_stage, flagged_pages, chunk_count, facts counts, notes.
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Chunk(UUIDPkMixin, TenantMixin, TimestampsMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        enum_check("lang", CHUNK_LANGS),
        Index(None, "document_id", "ordinal"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv_gin", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_text_norm_trgm",
            "text_norm",
            postgresql_using="gin",
            postgresql_ops={"text_norm": "gin_trgm_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)  # order within the document
    page: Mapped[int | None] = mapped_column(Integer)  # 1-based; sheet number for XLSX
    heading: Mapped[str | None] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)
    text_norm: Mapped[str] = mapped_column(Text)  # app.kb.text.normalize(text)
    lang: Mapped[str] = mapped_column(String(10))
    tokens: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, text_norm)", persisted=True)
    )
    suspicious: Mapped[bool] = mapped_column(Boolean, server_default="false")
