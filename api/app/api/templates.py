"""WhatsApp template manager (step 6.5, PLAN §14 Templates). Staff read; admin+ write.

Drafts are edited locally; `submit` sends one to Meta (`/{waba_id}/message_templates`) → pending;
status changes arrive by webhook (`message_template_status_update`) or `sync` (poll). Approved
templates are immutable here — edit = new name (Meta rule)."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import AdminCtx, SessionDep, SettingsDep, StaffCtx, WaClientDep, audit_mutations
from app.channels.whatsapp.client import WhatsAppError
from app.channels.whatsapp.templates import (
    TemplateError,
    default_rows,
    meta_language,
    meta_name,
    submit_payload,
    validate,
)
from app.models.core import Institution
from app.models.templates import Template
from app.services.audit import audit_ctx
from app.services.whatsapp import TEMPLATE_STATUS_MAP

router = APIRouter(prefix="/templates", tags=["templates"], dependencies=[audit_mutations])
Lang = Literal["en", "ur", "roman_ur"]
Category = Literal["utility", "marketing"]
EDITABLE = ("draft", "rejected")


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    language: str
    category: str
    body: str
    variables: list[str]
    examples: list[str]
    status: str
    meta_name: str = ""
    meta_template_id: str | None
    rejected_reason: str | None
    submitted_at: dt.datetime | None
    updated_at: dt.datetime


def _out(t: Template) -> TemplateOut:
    out = TemplateOut.model_validate(t)
    out.meta_name = meta_name(t)
    return out


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    language: Lang
    category: Category = "utility"
    body: str = Field(min_length=1, max_length=1024)
    examples: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list)


class TemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category | None = None
    body: str | None = Field(default=None, min_length=1, max_length=1024)
    examples: list[Annotated[str, Field(max_length=200)]] | None = None


class SyncOut(BaseModel):
    updated: int
    remote: int


def _checked(name: str, body: str) -> list[str]:
    try:
        return validate(name, body)
    except TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


async def _get(session: SessionDep, template_id: uuid.UUID) -> Template:
    tpl = await session.get(Template, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return tpl


@router.get("")
async def list_templates(
    ctx: StaffCtx,
    session: SessionDep,
    name: str | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[TemplateOut]:
    stmt = select(Template).order_by(Template.name, Template.language)
    if name:
        stmt = stmt.where(Template.name == name)
    if status_:
        stmt = stmt.where(Template.status == status_)
    return [_out(t) for t in (await session.scalars(stmt)).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateIn, ctx: AdminCtx, request: Request, session: SessionDep
) -> TemplateOut:
    variables = _checked(body.name, body.body)
    exists = await session.scalar(
        select(Template.id).where(Template.name == body.name, Template.language == body.language)
    )
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Template already exists for this language")
    tpl = Template(
        name=body.name,
        language=body.language,
        category=body.category,
        body=body.body,
        variables=variables,
        examples=body.examples[: len(variables)],
    )
    session.add(tpl)
    await session.flush()
    await audit_ctx(
        session,
        ctx,
        request,
        action="template.create",
        entity="template",
        entity_id=tpl.id,
        after={"name": tpl.name, "language": tpl.language},
    )
    await session.refresh(tpl)
    return _out(tpl)


@router.post("/seed")
async def seed_templates(ctx: AdminCtx, request: Request, session: SessionDep) -> list[TemplateOut]:
    """Create the default EN/UR/Roman-Urdu set (drafts) where missing. Idempotent."""
    have = {(t.name, t.language) for t in (await session.scalars(select(Template))).all()}
    made = []
    for row in default_rows():
        if (row["name"], row["language"]) not in have:
            tpl = Template(**row)
            session.add(tpl)
            made.append(tpl)
    await session.flush()
    await audit_ctx(
        session,
        ctx,
        request,
        action="template.seed",
        entity="template",
        after={"created": len(made)},
    )
    for t in made:
        await session.refresh(t)
    return [_out(t) for t in made]


@router.patch("/{template_id}")
async def patch_template(
    template_id: uuid.UUID,
    body: TemplatePatch,
    ctx: AdminCtx,
    request: Request,
    session: SessionDep,
) -> TemplateOut:
    tpl = await _get(session, template_id)
    if tpl.status not in EDITABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only draft or rejected templates can be edited — create a new name instead",
        )
    before = {"body": tpl.body, "category": tpl.category, "status": tpl.status}
    if body.body is not None:
        tpl.variables = _checked(tpl.name, body.body)
        tpl.body = body.body
    if body.category is not None:
        tpl.category = body.category
    if body.examples is not None:
        tpl.examples = body.examples[: len(tpl.variables)]
    tpl.status, tpl.rejected_reason = "draft", None
    await audit_ctx(
        session,
        ctx,
        request,
        action="template.update",
        entity="template",
        entity_id=tpl.id,
        before=before,
        after={"body": tpl.body, "category": tpl.category, "status": tpl.status},
    )
    await session.flush()
    await session.refresh(tpl)
    return _out(tpl)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID, ctx: AdminCtx, request: Request, session: SessionDep
) -> None:
    tpl = await _get(session, template_id)
    if tpl.status not in EDITABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Submitted templates cannot be deleted here")
    await audit_ctx(
        session,
        ctx,
        request,
        action="template.delete",
        entity="template",
        entity_id=tpl.id,
        before={"name": tpl.name, "language": tpl.language},
    )
    await session.delete(tpl)


async def _waba(session: SessionDep, ctx: AdminCtx, settings: SettingsDep) -> str:
    inst = await session.get(Institution, ctx.institution_id)
    waba = (inst.waba_id if inst else None) or (
        settings.meta_waba_id if settings.env != "prod" else None
    )
    if not waba:
        raise HTTPException(status.HTTP_409_CONFLICT, "WhatsApp Business Account not connected")
    return waba


@router.post("/{template_id}/submit")
async def submit_template(
    template_id: uuid.UUID,
    ctx: AdminCtx,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    client: WaClientDep,
) -> TemplateOut:
    """Human approval (G11): an admin explicitly submits each template to Meta."""
    tpl = await _get(session, template_id)
    if tpl.status not in EDITABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Template is already {tpl.status}")
    if client is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "WhatsApp is not connected (META_ACCESS_TOKEN)"
        )
    waba = await _waba(session, ctx, settings)
    try:
        res = await client.create_template(waba, submit_payload(tpl))
    except WhatsAppError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Meta: {exc}") from None
    tpl.meta_template_id = str(res.get("id") or "") or None
    tpl.status = TEMPLATE_STATUS_MAP.get(str(res.get("status") or "PENDING").upper(), "pending")
    tpl.submitted_at, tpl.rejected_reason = dt.datetime.now(dt.UTC), None
    await audit_ctx(
        session,
        ctx,
        request,
        action="template.submit",
        entity="template",
        entity_id=tpl.id,
        after={"meta_name": meta_name(tpl), "status": tpl.status},
    )
    await session.flush()
    await session.refresh(tpl)
    return _out(tpl)


@router.post("/sync")
async def sync_templates(
    ctx: AdminCtx,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    client: WaClientDep,
) -> SyncOut:
    """Poll Meta for template statuses (complements the status webhook)."""
    if client is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "WhatsApp is not connected (META_ACCESS_TOKEN)"
        )
    waba = await _waba(session, ctx, settings)
    try:
        remote = await client.list_templates(waba)
    except WhatsAppError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Meta: {exc}") from None
    by_key = {(r.get("name"), r.get("language")): r for r in remote}
    updated = 0
    for tpl in (await session.scalars(select(Template))).all():
        r = by_key.get((meta_name(tpl), meta_language(tpl.language)))
        if r is None:
            continue
        new_status = TEMPLATE_STATUS_MAP.get(str(r.get("status") or "").upper())
        if new_status and (new_status != tpl.status or not tpl.meta_template_id):
            tpl.status = new_status
            tpl.meta_template_id = str(r.get("id") or tpl.meta_template_id or "") or None
            reason = r.get("rejected_reason")
            tpl.rejected_reason = reason if new_status == "rejected" and reason != "NONE" else None
            updated += 1
    request.state.audited = True  # status mirror of Meta, not a user edit
    return SyncOut(updated=updated, remote=len(remote))
