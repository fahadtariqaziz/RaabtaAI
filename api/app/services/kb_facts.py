"""Facts lifecycle (step 2.6.3–2.6.4): pending rows from ingestion → admin approve/edit/reject →
only `approved` rows are served. Any change to what is served bumps `institutions.facts_version`.
Also: idempotent insert per source document, supersede on re-upload, playground lookup."""

import datetime as dt
import re
import uuid
from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantContext
from app.kb.citations import Citation, make_quote
from app.kb.text import normalize
from app.models.facts import FACT_MODELS, FactMixin
from app.models.kb import Document
from app.schemas.kb import FactOut, FactPatch
from app.services.audit import audit_ctx
from app.services.kb_documents import bump_facts_version

Frequency = Literal["one_time", "monthly", "quarterly", "annual", "per_semester"]


class _Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FeeItemFields(_Fields):
    class_name: str | None = Field(default=None, max_length=120)
    program_name: str | None = Field(default=None, max_length=200)
    head: str = Field(min_length=1, max_length=160)
    amount_pkr: int = Field(ge=0, le=100_000_000)
    frequency: Frequency


class ProgramFields(_Fields):
    name: str = Field(min_length=1, max_length=200)
    level: str | None = Field(default=None, max_length=80)
    duration: str | None = Field(default=None, max_length=80)
    eligibility: str | None = None
    deadline: dt.date | None = None
    seats: int | None = Field(default=None, ge=0)


class KeyDateFields(_Fields):
    event: str = Field(min_length=1, max_length=200)
    date: dt.date
    end_date: dt.date | None = None


class ScholarshipFields(_Fields):
    name: str = Field(min_length=1, max_length=200)
    rule: str | None = None
    amount: str | None = Field(default=None, max_length=120)


class TransportRouteFields(_Fields):
    name: str = Field(min_length=1, max_length=120)
    areas: str | None = None
    monthly_pkr: int = Field(ge=0, le=10_000_000)


FIELD_MODELS: dict[str, type[_Fields]] = {
    "fee_items": FeeItemFields,
    "programs": ProgramFields,
    "key_dates": KeyDateFields,
    "scholarships": ScholarshipFields,
    "transport_routes": TransportRouteFields,
}
COMMON = ("status", "notes", "academic_year")
# Columns searched by the playground's lexical facts lookup.
TEXT_COLUMNS: dict[str, tuple[str, ...]] = {
    "fee_items": ("class_name", "program_name", "head", "notes"),
    "programs": ("name", "level", "eligibility"),
    "key_dates": ("event", "notes"),
    "scholarships": ("name", "rule"),
    "transport_routes": ("name", "areas"),
}


class FactError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def model_for(kind: str) -> type[FactMixin]:
    try:
        return FACT_MODELS[kind]
    except KeyError:
        raise FactError(404, f"unknown fact kind {kind!r}") from None


def fields_of(kind: str, row: FactMixin) -> dict[str, Any]:
    return {name: getattr(row, name) for name in FIELD_MODELS[kind].model_fields}


def _jsonable(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in values.items()}


async def _titles(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(select(Document.id, Document.title).where(Document.id.in_(ids)))
    return {r[0]: r[1] for r in rows.all()}


def to_out(kind: str, row: FactMixin, titles: dict[uuid.UUID, str]) -> FactOut:
    source = None
    if row.source_document_id is not None and row.source_document_id in titles:
        source = Citation(
            document_id=row.source_document_id,
            title=titles[row.source_document_id],
            page=row.source_page,
            quote=make_quote(row.source_quote) if row.source_quote else None,
        )
    return FactOut(
        id=row.id,
        kind=kind,
        status=row.status,
        origin=row.origin,
        academic_year=row.academic_year,
        notes=row.notes,
        fields=_jsonable(fields_of(kind, row)),
        source=source,
        approved_at=row.approved_at,
        updated_at=row.updated_at,
    )


async def outs(session: AsyncSession, kind: str, rows: list[FactMixin]) -> list[FactOut]:
    titles = await _titles(session, {r.source_document_id for r in rows if r.source_document_id})
    return [to_out(kind, r, titles) for r in rows]


async def list_facts(
    session: AsyncSession, kind: str, status: str | None, document_id: uuid.UUID | None
) -> list[FactOut]:
    model = model_for(kind)
    stmt = select(model).order_by(model.created_at, model.ordinal, model.id)
    if status:
        stmt = stmt.where(model.status == status)
    if document_id:
        stmt = stmt.where(model.source_document_id == document_id)
    rows = list((await session.scalars(stmt)).all())
    return await outs(session, kind, rows)


def _snapshot(kind: str, row: FactMixin) -> dict[str, Any]:
    return _jsonable({**fields_of(kind, row), **{c: getattr(row, c) for c in COMMON}})


async def patch_fact(
    session: AsyncSession,
    ctx: TenantContext,
    request: Request,
    kind: str,
    fact_id: uuid.UUID,
    body: FactPatch,
) -> FactOut:
    model = model_for(kind)
    row = await session.get(model, fact_id)
    if row is None:
        raise FactError(404, "Fact not found")
    before = _snapshot(kind, row)
    was_served = row.status == "approved"
    if body.fields:
        merged = {**fields_of(kind, row), **body.fields}
        try:
            valid = FIELD_MODELS[kind].model_validate(merged)
        except ValidationError as exc:
            raise FactError(422, exc.errors(include_url=False, include_input=False)) from None
        for name, value in valid.model_dump().items():
            setattr(row, name, value)
    if body.notes is not None:
        row.notes = body.notes or None
    if body.academic_year is not None:
        row.academic_year = body.academic_year or None
    if row.status == "superseded" and body.status:
        raise FactError(409, "fact belongs to a superseded document version")
    if body.status:
        _set_status(row, body.status, ctx.user_id)
    after = _snapshot(kind, row)
    if before == after:
        return (await outs(session, kind, [row]))[0]
    if was_served or row.status == "approved":
        await bump_facts_version(session, ctx.institution_id)
    await audit_ctx(
        session,
        ctx,
        request,
        action=f"kb.fact.{body.status or 'edit'}",
        entity=kind,
        entity_id=row.id,
        before=before,
        after=after,
    )
    await session.flush()
    await session.refresh(row)
    return (await outs(session, kind, [row]))[0]


def _set_status(row: FactMixin, status: str, user_id: uuid.UUID) -> None:
    row.status = status
    if status == "approved":
        row.approved_by = user_id
        row.approved_at = dt.datetime.now(dt.UTC)
    else:
        row.approved_by = None
        row.approved_at = None


async def bulk_status(
    session: AsyncSession,
    ctx: TenantContext,
    request: Request,
    kind: str,
    ids: list[uuid.UUID],
    status: str,
) -> int:
    model = model_for(kind)
    rows = list(
        (
            await session.scalars(
                select(model).where(model.id.in_(ids), model.status != "superseded")
            )
        ).all()
    )
    changed = [r for r in rows if r.status != status]
    if not changed:
        return 0
    touches_served = any(r.status == "approved" for r in changed) or status == "approved"
    for row in changed:
        _set_status(row, status, ctx.user_id)
    if touches_served:
        await bump_facts_version(session, ctx.institution_id)
    await audit_ctx(
        session,
        ctx,
        request,
        action=f"kb.fact.bulk_{status}",
        entity=kind,
        after={"ids": [str(r.id) for r in changed], "status": status},
    )
    await session.flush()
    return len(changed)


async def replace_document_facts(
    session: AsyncSession,
    institution_id: uuid.UUID,
    document_id: uuid.UUID,
    rows: dict[str, list[dict[str, Any]]],
    origin: str,
) -> dict[str, int]:
    """Idempotent per document: drop this document's *pending* rows of `origin`, insert new
    pending rows. Approved/rejected rows (admin decisions) are kept."""
    counts: dict[str, int] = {}
    for kind, items in rows.items():
        model = model_for(kind)
        await session.execute(
            delete(model).where(
                model.source_document_id == document_id,
                model.status == "pending",
                model.origin == origin,
            )
        )
        for ordinal, item in enumerate(items):
            values = dict(item)
            valid = FIELD_MODELS[kind].model_validate(
                {k: values.pop(k) for k in FIELD_MODELS[kind].model_fields if k in values}
            )
            factory: Any = model  # declarative constructor (mixin has no typed __init__)
            session.add(
                factory(
                    institution_id=institution_id,
                    source_document_id=document_id,
                    origin=origin,
                    status="pending",
                    ordinal=ordinal,
                    **valid.model_dump(),
                    **{k: v for k, v in values.items() if k in _EXTRA},
                )
            )
        counts[kind] = len(items)
    await session.flush()
    return counts


_EXTRA = frozenset({"academic_year", "notes", "source_page", "source_quote"})


async def supersede_document_facts(
    session: AsyncSession, institution_id: uuid.UUID, old_document_id: uuid.UUID
) -> bool:
    """Old version's approved facts → `superseded` (no longer served); pending/rejected dropped.
    Returns True if served facts changed (caller bumps facts_version)."""
    served_changed = False
    for model in FACT_MODELS.values():
        result = await session.execute(
            update(model)
            .where(model.source_document_id == old_document_id, model.status == "approved")
            .values(status="superseded")
        )
        served_changed |= bool(getattr(result, "rowcount", 0))
        await session.execute(
            delete(model).where(
                model.source_document_id == old_document_id,
                model.status.in_(("pending", "rejected")),
            )
        )
    return served_changed


async def approve_all(session: AsyncSession, institution_id: uuid.UUID) -> int:
    """Demo/seed helper: approve every pending fact (CLI `ingest-seeds`)."""
    total = 0
    now = dt.datetime.now(dt.UTC)
    for model in FACT_MODELS.values():
        result = await session.execute(
            update(model)
            .where(model.status == "pending")
            .values(status="approved", approved_at=now)
        )
        total += int(getattr(result, "rowcount", 0) or 0)
    if total:
        await bump_facts_version(session, institution_id)
    return total


async def match_facts(
    session: AsyncSession, terms: list[str], *, limit_per_kind: int = 5
) -> list[FactOut]:
    """Approved facts whose text columns contain query terms, ranked by how many distinct terms
    match as whole words (playground view; the agent's typed `get_*` tools come in Phase 3)."""
    usable = [t for t in dict.fromkeys(terms) if t.isalnum() and (len(t) >= 3 or t.isdigit())][:12]
    if not usable:
        return []
    found: list[FactOut] = []
    for kind, model in FACT_MODELS.items():
        cols = [getattr(model, c) for c in TEXT_COLUMNS[kind]]
        cond = or_(*[col.ilike(f"%{t}%") for col in cols for t in usable])
        stmt = select(model).where(model.status == "approved", cond).limit(200)
        rows = list((await session.scalars(stmt)).all())

        def score(row: FactMixin, kind: str = kind) -> int:
            text = normalize(" ".join(str(getattr(row, c) or "") for c in TEXT_COLUMNS[kind]))
            tokens = set(text.split()) | set(re.findall(r"\w+", text))
            return sum(1 for t in usable if t in tokens)

        ranked = sorted(rows, key=lambda r: (-score(r), r.ordinal, str(r.id)))
        found.extend(await outs(session, kind, ranked[:limit_per_kind]))
    return found
