"""Ingestion pipeline (step 2.8, PLAN §5 STEER): uploaded → parsing → chunking → embedding →
extracting → ready (or failed). Deterministic workflow, not LLM-decided.

- Each stage runs in its own tenant-scoped transaction and records `documents.status`, so a crash
  resumes at the interrupted stage; a failure stores `error` + `meta.failed_stage` and a retry
  (re-index endpoint / re-enqueue) resumes there.
- Stages are idempotent: parse output is stored next to the original (`parsed.json`); chunking
  replaces this document's chunks; embedding only fills missing/stale vectors (committed per
  batch); extraction replaces this document's pending facts.
- `ready` is atomic: in one transaction the document becomes ready and every older version with
  the same title becomes `superseded` (its chunks deleted, its approved facts superseded), so
  search never sees both versions or neither.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.tenancy import tenant_session
from app.kb.blobstore import BlobStore
from app.kb.chunking import chunk_blocks
from app.kb.embeddings import EmbeddingProvider
from app.kb.facts_extractor import extract_facts
from app.kb.facts_tables import facts_from_spreadsheet
from app.kb.parsers import ParsedDoc, parse
from app.llm.claude import ClaudeClient, ParseResult
from app.llm.runs import run_record, to_row
from app.models.conversations import LlmRun
from app.models.kb import Chunk, Document
from app.prompts import load_prompt
from app.services.kb_documents import bump_facts_version
from app.services.kb_facts import replace_document_facts, supersede_document_facts

log = structlog.get_logger(__name__)

STAGES = ("parsing", "chunking", "embedding", "extracting", "finalizing")
EMBED_BATCH = 64


@dataclass
class IngestDeps:
    sessionmaker: async_sessionmaker[AsyncSession]
    blobstore: BlobStore
    settings: Settings
    provider: EmbeddingProvider
    llm: ClaudeClient | None = None  # needed only for KB_FACTS_LLM / KB_VISION_OCR


class StageError(RuntimeError):
    pass


def parsed_key(doc: Document) -> str:
    return doc.file_path.rsplit("/", 1)[0] + "/parsed.json"


def _start_stage(doc: Document) -> str | None:
    if doc.status == "uploaded":
        return STAGES[0]
    if doc.status in STAGES:
        return doc.status
    if doc.status == "failed":
        stage = doc.meta.get("failed_stage")
        return stage if stage in STAGES else STAGES[0]
    return None  # ready / superseded: nothing to do


async def ingest_document(deps: IngestDeps, institution_id: uuid.UUID, doc_id: uuid.UUID) -> str:
    """Run (or resume) the pipeline for one document. Returns the final status."""
    async with tenant_session(deps.sessionmaker, institution_id) as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            raise StageError(f"document {doc_id} not found for institution {institution_id}")
        start = _start_stage(doc)
    if start is None:
        return doc.status
    for stage in STAGES[STAGES.index(start) :]:
        if stage != "finalizing":  # finalizing is internal; it ends in `ready` atomically
            async with tenant_session(deps.sessionmaker, institution_id) as session:
                await session.execute(
                    update(Document).where(Document.id == doc_id).values(status=stage, error=None)
                )
        try:
            await _RUNNERS[stage](deps, institution_id, doc_id)
        except Exception as exc:
            log.warning("kb.ingest.failed", document_id=str(doc_id), stage=stage, error=str(exc))
            async with tenant_session(deps.sessionmaker, institution_id) as session:
                doc = await session.get(Document, doc_id)
                if doc is not None:
                    doc.status = "failed"
                    doc.error = f"{stage}: {exc}"[:2000]
                    doc.meta = {**doc.meta, "failed_stage": stage}
            return "failed"
    log.info("kb.ingest.ready", document_id=str(doc_id))
    return "ready"


async def _load(session: AsyncSession, doc_id: uuid.UUID) -> Document:
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise StageError("document disappeared")
    return doc


async def _parsed(deps: IngestDeps, doc: Document) -> ParsedDoc:
    raw = await deps.blobstore.get(parsed_key(doc))
    return ParsedDoc.from_json(json.loads(raw))


async def stage_parse(deps: IngestDeps, institution_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    async with tenant_session(deps.sessionmaker, institution_id) as session:
        doc = await _load(session, doc_id)
        data = await deps.blobstore.get(doc.file_path)
        parsed = await asyncio.to_thread(parse, doc.kind, data)
        runs: list[ParseResult[Any]] = []
        if parsed.flagged_pages and deps.settings.kb_vision_ocr and deps.llm is not None:
            from app.kb.ocr import ocr_flagged_pages

            parsed, runs = await ocr_flagged_pages(deps.llm, data, parsed)
        if not any(b.text.strip() for b in parsed.blocks):
            raise StageError("no text could be extracted (scanned document? enable KB_VISION_OCR)")
        await deps.blobstore.put(
            parsed_key(doc), json.dumps(parsed.to_json(), ensure_ascii=False).encode()
        )
        doc.pages = parsed.pages
        doc.meta = {
            **doc.meta,
            "flagged_pages": parsed.flagged_pages,
            "parse_notes": parsed.notes[:50],
        }
        for run in runs:
            session.add(_llm_run(institution_id, "kb_vision_ocr", run, None))


async def stage_chunk(deps: IngestDeps, institution_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    async with tenant_session(deps.sessionmaker, institution_id) as session:
        doc = await _load(session, doc_id)
        drafts = chunk_blocks((await _parsed(deps, doc)).blocks)
        if not drafts:
            raise StageError("document produced no chunks")
        await session.execute(delete(Chunk).where(Chunk.document_id == doc_id))
        for d in drafts:
            session.add(
                Chunk(
                    institution_id=institution_id,
                    document_id=doc_id,
                    ordinal=d.ordinal,
                    page=d.page,
                    heading=d.heading,
                    text=d.text,
                    text_norm=d.text_norm,
                    lang=d.lang,
                    tokens=d.tokens,
                    suspicious=d.suspicious,
                )
            )
        doc.meta = {
            **doc.meta,
            "chunk_count": len(drafts),
            "suspicious_chunks": sum(d.suspicious for d in drafts),
        }


def embed_text(title: str, chunk: Chunk) -> str:
    return "\n".join(p for p in (title, chunk.heading, chunk.text) if p)


async def stage_embed(deps: IngestDeps, institution_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    provider = deps.provider
    while True:  # one transaction per batch → resumable mid-document
        async with tenant_session(deps.sessionmaker, institution_id) as session:
            doc = await _load(session, doc_id)
            batch = list(
                (
                    await session.scalars(
                        select(Chunk)
                        .where(
                            Chunk.document_id == doc_id,
                            (Chunk.embedding.is_(None))
                            | (Chunk.embedding_model.is_distinct_from(provider.name)),
                        )
                        .order_by(Chunk.ordinal)
                        .limit(EMBED_BATCH)
                    )
                ).all()
            )
            if not batch:
                return
            vectors = await provider.embed([embed_text(doc.title, c) for c in batch], "document")
            if len(vectors) != len(batch):
                raise StageError("embedding provider returned a wrong number of vectors")
            for chunk, vec in zip(batch, vectors, strict=True):
                chunk.embedding = vec
                chunk.embedding_model = provider.name


async def stage_extract(deps: IngestDeps, institution_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    async with tenant_session(deps.sessionmaker, institution_id) as session:
        doc = await _load(session, doc_id)
        if doc.kind in ("xlsx", "csv"):
            data = await deps.blobstore.get(doc.file_path)
            table = await asyncio.to_thread(facts_from_spreadsheet, doc.kind, data)
            rows = {"fee_items": table.fee_items, "transport_routes": table.transport_routes}
            counts = await replace_document_facts(session, institution_id, doc_id, rows, "table")
            doc.meta = {**doc.meta, "facts": counts, "facts_skipped": table.skipped[:50]}
            return
        if not deps.settings.kb_facts_llm or deps.llm is None:
            doc.meta = {**doc.meta, "facts": "skipped (KB_FACTS_LLM is off)"}
            return
        extracted = await extract_facts(deps.llm, await _parsed(deps, doc), doc.title)
        counts = await replace_document_facts(
            session, institution_id, doc_id, extracted.rows, "llm"
        )
        for run in extracted.runs:
            prompt_hash = load_prompt("facts_extractor").hash
            session.add(_llm_run(institution_id, "facts_extractor", run, prompt_hash))
        doc.meta = {**doc.meta, "facts": counts, "facts_dropped": extracted.dropped[:50]}


async def stage_finalize(deps: IngestDeps, institution_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    async with tenant_session(deps.sessionmaker, institution_id) as session:
        doc = await _load(session, doc_id)
        older = list(
            (
                await session.scalars(
                    select(Document).where(
                        Document.title == doc.title,
                        Document.id != doc.id,
                        Document.version < doc.version,
                        Document.status != "superseded",
                    )
                )
            ).all()
        )
        served_changed = False
        for old in older:
            await session.execute(delete(Chunk).where(Chunk.document_id == old.id))
            served_changed |= await supersede_document_facts(session, institution_id, old.id)
            old.status = "superseded"
        if served_changed:
            await bump_facts_version(session, institution_id)
        doc.status = "ready"
        doc.error = None
        doc.meta = {k: v for k, v in doc.meta.items() if k != "failed_stage"}
        if older:
            doc.meta = {**doc.meta, "superseded": [str(o.id) for o in older]}


_RUNNERS = {
    "parsing": stage_parse,
    "chunking": stage_chunk,
    "embedding": stage_embed,
    "extracting": stage_extract,
    "finalizing": stage_finalize,
}


def _llm_run(
    institution_id: uuid.UUID, node: str, run: ParseResult[Any], prompt_hash: str | None
) -> LlmRun:
    return to_row(institution_id, run_record(node, run, prompt_hash=prompt_hash))


async def reembed_all(deps: IngestDeps, institution_id: uuid.UUID) -> int:
    """Re-embed every chunk of an institution with `deps.provider` (provider switch / bake-off)."""
    async with tenant_session(deps.sessionmaker, institution_id) as session:
        doc_ids = list(
            (await session.scalars(select(Document.id).where(Document.status == "ready"))).all()
        )
    for doc_id in doc_ids:
        await stage_embed(deps, institution_id, doc_id)
    return len(doc_ids)


async def enqueue_ingest(redis: Any, institution_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    await redis.enqueue_job("ingest_document_job", str(institution_id), str(doc_id))
