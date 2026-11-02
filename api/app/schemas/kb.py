"""Knowledge-base API schemas (PLAN §14 KB)."""

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.kb.citations import Citation

FactKind = Literal["programs", "fee_items", "key_dates", "scholarships", "transport_routes"]
FactStatus = Literal["pending", "approved", "rejected", "superseded"]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    kind: str
    filename: str
    mime: str
    size_bytes: int
    checksum: str
    pages: int | None
    version: int
    supersedes_id: uuid.UUID | None
    status: str
    error: str | None
    meta: dict[str, Any]
    created_at: dt.datetime
    updated_at: dt.datetime


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    ordinal: int
    page: int | None
    heading: str | None
    text: str
    lang: str
    tokens: int
    suspicious: bool
    embedded: bool


class FactOut(BaseModel):
    """One fact row of any kind: common columns + kind-specific `fields`."""

    id: uuid.UUID
    kind: FactKind
    status: FactStatus
    origin: str
    academic_year: str | None
    notes: str | None
    fields: dict[str, Any]
    source: Citation | None
    approved_at: dt.datetime | None
    updated_at: dt.datetime


class FactPatch(BaseModel):
    """Edit one fact (`fields` are validated per kind) and/or change its status."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "approved", "rejected"] | None = None
    fields: dict[str, Any] | None = None
    notes: str | None = None
    academic_year: str | None = Field(default=None, max_length=16)


class FactsBulkStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    status: Literal["approved", "rejected"]


class FactsBulkOut(BaseModel):
    updated: int


class PlaygroundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    extra_queries: list[str] = Field(default_factory=list, max_length=2)
    top_k: int = Field(default=5, ge=1, le=20)


class PlaygroundChunk(BaseModel):
    chunk_id: uuid.UUID
    score: float
    legs: dict[str, int]  # leg name -> rank (1-based) in that leg
    heading: str | None
    text: str
    tokens: int
    citation: Citation


class PlaygroundOut(BaseModel):
    queries: list[str]
    chunks: list[PlaygroundChunk]
    facts: list[FactOut]
    packed_tokens: int
