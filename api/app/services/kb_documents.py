"""KB document lifecycle (step 2.1): upload (sniff, cap, checksum dedupe, versioning), list, get,
delete, re-index. Runs in a tenant-scoped session; ingestion itself is the arq pipeline
(`app.kb.ingest`)."""

import hashlib
import re
import uuid
from pathlib import PurePath

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantContext
from app.kb.blobstore import BlobStore
from app.kb.sniff import UnsupportedFileError, sniff
from app.models.core import Institution
from app.models.facts import FACT_MODELS
from app.models.kb import Chunk, Document
from app.services.audit import audit_ctx, snapshot

IN_PROGRESS = frozenset({"uploaded", "parsing", "chunking", "embedding", "extracting"})
DOC_FIELDS = ("title", "kind", "filename", "version", "checksum", "status")


class DocumentError(Exception):
    def __init__(self, status_code: int, detail: str | dict[str, str]) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def blob_key(institution_id: uuid.UUID, document_id: uuid.UUID, kind: str) -> str:
    return f"{institution_id}/documents/{document_id}/original.{kind}"


def _clean_title(title: str | None, filename: str) -> str:
    raw = (title or PurePath(filename).stem or "Untitled").strip()
    return re.sub(r"\s+", " ", raw)[:200]


async def bump_facts_version(session: AsyncSession, institution_id: uuid.UUID) -> None:
    """Invalidate the cached tenant prompt block (PLAN §7) whenever served facts change."""
    await session.execute(
        update(Institution)
        .where(Institution.id == institution_id)
        .values(facts_version=Institution.facts_version + 1)
    )


async def create_document(
    session: AsyncSession,
    blobstore: BlobStore,
    *,
    institution_id: uuid.UUID,
    user_id: uuid.UUID | None,
    data: bytes,
    filename: str,
    title: str | None,
) -> Document:
    """Validate, dedupe, version and store one file; returns the new `uploaded` document row."""
    try:
        sniffed = sniff(data, filename)
    except UnsupportedFileError as exc:
        raise DocumentError(415, str(exc)) from None
    checksum = hashlib.sha256(data).hexdigest()
    duplicate = await session.scalar(
        select(Document).where(
            Document.checksum == checksum, Document.status.not_in(("superseded", "failed"))
        )
    )
    if duplicate is not None:
        raise DocumentError(
            409, {"message": "identical file already uploaded", "document_id": str(duplicate.id)}
        )
    clean_title = _clean_title(title, filename)
    previous = await session.scalar(
        select(Document)
        .where(Document.title == clean_title, Document.status != "superseded")
        .order_by(Document.version.desc())
        .limit(1)
    )
    if previous is not None and previous.status in IN_PROGRESS:
        raise DocumentError(409, "previous version is still being processed; try again shortly")
    max_version = await session.scalar(
        select(func.max(Document.version)).where(Document.title == clean_title)
    )
    doc_id = uuid.uuid4()
    doc = Document(
        id=doc_id,
        institution_id=institution_id,
        title=clean_title,
        kind=sniffed.kind,
        filename=PurePath(filename).name[:255] or f"upload.{sniffed.kind}",
        file_path=blob_key(institution_id, doc_id, sniffed.kind),
        mime=sniffed.mime,
        size_bytes=len(data),
        checksum=checksum,
        version=(max_version or 0) + 1,
        supersedes_id=previous.id if previous is not None else None,
        status="uploaded",
        meta={},
        uploaded_by=user_id,
    )
    session.add(doc)
    await session.flush()
    await blobstore.put(doc.file_path, data)
    return doc


async def upload(
    session: AsyncSession,
    ctx: TenantContext,
    request: Request,
    blobstore: BlobStore,
    *,
    data: bytes,
    filename: str,
    title: str | None,
) -> Document:
    doc = await create_document(
        session,
        blobstore,
        institution_id=ctx.institution_id,
        user_id=ctx.user_id,
        data=data,
        filename=filename,
        title=title,
    )
    await audit_ctx(
        session,
        ctx,
        request,
        action="kb.document.upload",
        entity="document",
        entity_id=doc.id,
        after=snapshot(doc, DOC_FIELDS),
    )
    return doc


async def list_documents(session: AsyncSession, *, include_superseded: bool) -> list[Document]:
    stmt = select(Document).order_by(Document.title, Document.version.desc())
    if not include_superseded:
        stmt = stmt.where(Document.status != "superseded")
    return list((await session.scalars(stmt)).all())


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise DocumentError(404, "Document not found")
    return doc


async def list_chunks(session: AsyncSession, document_id: uuid.UUID) -> list[Chunk]:
    await get_document(session, document_id)
    stmt = select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal)
    return list((await session.scalars(stmt)).all())


async def delete_document(
    session: AsyncSession,
    ctx: TenantContext,
    request: Request,
    blobstore: BlobStore,
    document_id: uuid.UUID,
) -> None:
    doc = await get_document(session, document_id)
    approved = 0
    for model in FACT_MODELS.values():
        approved += len(
            (
                await session.scalars(
                    select(model.id).where(
                        model.source_document_id == doc.id, model.status == "approved"
                    )
                )
            ).all()
        )
    before = snapshot(doc, DOC_FIELDS)
    key = doc.file_path
    await session.delete(doc)  # chunks + facts cascade (FK ON DELETE CASCADE)
    if approved:
        await bump_facts_version(session, ctx.institution_id)
    await audit_ctx(
        session,
        ctx,
        request,
        action="kb.document.delete",
        entity="document",
        entity_id=document_id,
        before={**before, "approved_facts_removed": approved},
    )
    await session.flush()
    await blobstore.delete(key)


async def reindex(
    session: AsyncSession,
    ctx: TenantContext,
    request: Request,
    blobstore: BlobStore,
    document_id: uuid.UUID,
) -> Document:
    """`ready` → a new version of the same file (old version keeps serving until the new one is
    ready, then is superseded atomically). `failed` → resume the pipeline on the same row."""
    doc = await get_document(session, document_id)
    if doc.status in IN_PROGRESS:
        raise DocumentError(409, "document is already being processed")
    newer = await session.scalar(
        select(Document.id).where(
            Document.title == doc.title,
            Document.version > doc.version,
            Document.status != "superseded",
        )
    )
    if doc.status == "superseded" or newer is not None:
        raise DocumentError(409, "a newer version exists; re-index that one")
    if doc.status == "failed":
        target = doc  # the pipeline resumes from meta["failed_stage"]
    else:
        data = await blobstore.get(doc.file_path)
        new_id = uuid.uuid4()
        max_version = await session.scalar(
            select(func.max(Document.version)).where(Document.title == doc.title)
        )
        target = Document(
            id=new_id,
            institution_id=ctx.institution_id,
            title=doc.title,
            kind=doc.kind,
            filename=doc.filename,
            file_path=blob_key(ctx.institution_id, new_id, doc.kind),
            mime=doc.mime,
            size_bytes=doc.size_bytes,
            checksum=doc.checksum,
            version=(max_version or 0) + 1,
            supersedes_id=doc.id,
            status="uploaded",
            meta={"reindex_of": str(doc.id)},
            uploaded_by=ctx.user_id,
        )
        session.add(target)
        await session.flush()
        await blobstore.put(target.file_path, data)
    await audit_ctx(
        session,
        ctx,
        request,
        action="kb.document.reindex",
        entity="document",
        entity_id=target.id,
        after={"source_document_id": str(doc.id), "version": target.version},
    )
    return target
