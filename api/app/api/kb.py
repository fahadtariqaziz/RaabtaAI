"""`/api/v1/kb` — knowledge base: documents, chunks, facts approval, retrieval playground
(PLAN §14 KB). Staff+ can view; admin+ uploads, deletes, re-indexes and approves facts."""

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from app.api.deps import (
    AdminCtx,
    BlobStoreDep,
    RedisDep,
    SessionDep,
    SettingsDep,
    StaffCtx,
    audit_mutations,
)
from app.kb.embeddings import make_provider
from app.kb.ingest import enqueue_ingest
from app.kb.search import expand, pack, search
from app.models.kb import Chunk
from app.schemas.kb import (
    ChunkOut,
    DocumentOut,
    FactKind,
    FactOut,
    FactPatch,
    FactsBulkOut,
    FactsBulkStatus,
    FactStatus,
    PlaygroundChunk,
    PlaygroundIn,
    PlaygroundOut,
)
from app.services import kb_documents as docs
from app.services import kb_facts as facts

router = APIRouter(prefix="/kb", tags=["kb"], dependencies=[audit_mutations])
READ_CHUNK = 1024 * 1024


def _http(exc: docs.DocumentError | facts.FactError) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    parts: list[bytes] = []
    size = 0
    while chunk := await file.read(READ_CHUNK):
        size += len(chunk)
        if size > limit:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"file exceeds {limit // (1024 * 1024)} MB"
            )
        parts.append(chunk)
    return b"".join(parts)


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    ctx: AdminCtx,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    blobstore: BlobStoreDep,
    redis: RedisDep,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=200)] = None,
) -> DocumentOut:
    data = await _read_capped(file, settings.kb_max_upload_mb * 1024 * 1024)
    try:
        doc = await docs.upload(
            session,
            ctx,
            request,
            blobstore,
            data=data,
            filename=file.filename or "upload",
            title=title,
        )
    except docs.DocumentError as exc:
        raise _http(exc) from None
    # Background tasks run after the response, i.e. after the transaction committed.
    background.add_task(enqueue_ingest, redis, ctx.institution_id, doc.id)
    return DocumentOut.model_validate(doc)


@router.get("/documents")
async def list_documents(
    _: StaffCtx, session: SessionDep, include_superseded: bool = False
) -> list[DocumentOut]:
    rows = await docs.list_documents(session, include_superseded=include_superseded)
    return [DocumentOut.model_validate(d) for d in rows]


@router.get("/documents/{document_id}")
async def get_document(document_id: uuid.UUID, _: StaffCtx, session: SessionDep) -> DocumentOut:
    try:
        return DocumentOut.model_validate(await docs.get_document(session, document_id))
    except docs.DocumentError as exc:
        raise _http(exc) from None


def _chunk_out(c: Chunk) -> ChunkOut:
    return ChunkOut(
        id=c.id,
        ordinal=c.ordinal,
        page=c.page,
        heading=c.heading,
        text=c.text,
        lang=c.lang,
        tokens=c.tokens,
        suspicious=c.suspicious,
        embedded=c.embedding is not None,
    )


@router.get("/documents/{document_id}/chunks")
async def list_chunks(document_id: uuid.UUID, _: StaffCtx, session: SessionDep) -> list[ChunkOut]:
    try:
        return [_chunk_out(c) for c in await docs.list_chunks(session, document_id)]
    except docs.DocumentError as exc:
        raise _http(exc) from None


@router.post("/documents/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document(
    document_id: uuid.UUID,
    ctx: AdminCtx,
    request: Request,
    session: SessionDep,
    blobstore: BlobStoreDep,
    redis: RedisDep,
    background: BackgroundTasks,
) -> DocumentOut:
    try:
        doc = await docs.reindex(session, ctx, request, blobstore, document_id)
    except docs.DocumentError as exc:
        raise _http(exc) from None
    background.add_task(enqueue_ingest, redis, ctx.institution_id, doc.id)
    return DocumentOut.model_validate(doc)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    ctx: AdminCtx,
    request: Request,
    session: SessionDep,
    blobstore: BlobStoreDep,
) -> None:
    try:
        await docs.delete_document(session, ctx, request, blobstore, document_id)
    except docs.DocumentError as exc:
        raise _http(exc) from None


@router.get("/facts/{kind}")
async def list_facts(
    kind: FactKind,
    _: StaffCtx,
    session: SessionDep,
    status_filter: Annotated[FactStatus | None, Query(alias="status")] = None,
    document_id: uuid.UUID | None = None,
) -> list[FactOut]:
    return await facts.list_facts(session, kind, status_filter, document_id)


@router.patch("/facts/{kind}")
async def bulk_fact_status(
    kind: FactKind, body: FactsBulkStatus, ctx: AdminCtx, request: Request, session: SessionDep
) -> FactsBulkOut:
    updated = await facts.bulk_status(session, ctx, request, kind, body.ids, body.status)
    return FactsBulkOut(updated=updated)


@router.patch("/facts/{kind}/{fact_id}")
async def patch_fact(
    kind: FactKind,
    fact_id: uuid.UUID,
    body: FactPatch,
    ctx: AdminCtx,
    request: Request,
    session: SessionDep,
) -> FactOut:
    try:
        return await facts.patch_fact(session, ctx, request, kind, fact_id, body)
    except facts.FactError as exc:
        raise _http(exc) from None


@router.post("/playground")
async def playground(
    body: PlaygroundIn, ctx: StaffCtx, request: Request, session: SessionDep, settings: SettingsDep
) -> PlaygroundOut:
    """Answer-less retrieval view: fused chunks (with citations) + matching approved facts."""
    request.state.audited = True  # read-only POST: no audit row
    queries = [body.query, *body.extra_queries]
    provider = make_provider(settings)
    hits = await search(session, ctx.institution_id, queries, provider, top_k=body.top_k)
    kept, used = pack(hits)
    terms = [t for q in queries for t in expand(q)]
    chunks = [
        PlaygroundChunk(
            chunk_id=h.chunk_id,
            score=round(h.score, 6),
            legs=h.legs,
            heading=h.heading,
            text=h.text,
            tokens=h.tokens,
            citation=h.citation(terms),
        )
        for h in kept
    ]
    return PlaygroundOut(
        queries=queries,
        chunks=chunks,
        facts=await facts.match_facts(session, terms),
        packed_tokens=used,
    )
