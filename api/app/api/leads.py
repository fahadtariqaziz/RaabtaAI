"""`/api/v1/leads` — admissions pipeline (PLAN §14 Leads; step 5.5). Staff+ read/write;
status/owner changes are audited with explicit before/after."""

import csv
import datetime as dt
import io
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, false, or_, select

from app.agent.tools.leads import normalize_pk_phone
from app.api.deps import SessionDep, StaffCtx, audit_mutations
from app.models.conversations import Booking, Conversation, Lead, Slot
from app.models.core import AuditLog, Membership, User
from app.models.enums import LEAD_STATUSES
from app.services.audit import audit_ctx, snapshot

router = APIRouter(prefix="/leads", tags=["leads"], dependencies=[audit_mutations])
LeadStatus = Literal["new", "contacted", "visit_booked", "applied", "admitted", "lost"]
LeadSource = Literal["widget", "whatsapp", "manual", "import"]
SORTS = {
    "created_at": Lead.created_at,
    "updated_at": Lead.updated_at,
    "next_followup_at": Lead.next_followup_at,
    "student_name": Lead.student_name,
}
AUDITED = ("status", "owner_user_id", "notes", "next_followup_at", "student_name", "phone")
CSV_FIELDS = (
    "id",
    "student_name",
    "guardian_name",
    "phone",
    "interest",
    "source",
    "status",
    "owner",
    "next_followup_at",
    "created_at",
    "notes",
)


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    contact_id: uuid.UUID | None
    student_name: str | None
    guardian_name: str | None
    phone: str | None
    interest: str | None
    source: str
    status: str
    owner_user_id: uuid.UUID | None
    notes: str | None
    next_followup_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class LeadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_name: str | None = Field(default=None, max_length=120)
    guardian_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    interest: str | None = Field(default=None, max_length=200)
    status: LeadStatus = "new"
    notes: str | None = Field(default=None, max_length=4000)
    next_followup_at: dt.datetime | None = None


class LeadPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_name: str | None = Field(default=None, max_length=120)
    guardian_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    interest: str | None = Field(default=None, max_length=200)
    status: LeadStatus | None = None
    owner_user_id: uuid.UUID | None = None
    clear_owner: bool = False
    notes: str | None = Field(default=None, max_length=4000)
    next_followup_at: dt.datetime | None = None


class TimelineItem(BaseModel):
    at: dt.datetime
    kind: str  # created | booking | conversation | audit
    text: str
    ref: str | None = None


class LeadDetail(LeadOut):
    owner_name: str | None
    bookings: list[dict[str, Any]]
    conversations: list[dict[str, Any]]
    timeline: list[TimelineItem]


def _phone(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    phone = normalize_pk_phone(raw)
    if phone is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid Pakistani phone number")
    return phone


def _query(
    status_: str | None, owner: str | None, source: str | None, q: str | None, uid: uuid.UUID
) -> Select[Lead]:
    stmt = select(Lead)
    if status_:
        stmt = stmt.where(Lead.status == status_)
    if owner == "me":
        stmt = stmt.where(Lead.owner_user_id == uid)
    elif owner == "none":
        stmt = stmt.where(Lead.owner_user_id.is_(None))
    if source:
        stmt = stmt.where(Lead.source == source)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Lead.student_name.ilike(like),
                Lead.guardian_name.ilike(like),
                Lead.phone.ilike(like),
                Lead.interest.ilike(like),
            )
        )
    return stmt


@router.get("")
async def list_leads(
    ctx: StaffCtx,
    session: SessionDep,
    status_: Annotated[LeadStatus | None, Query(alias="status")] = None,
    owner: Literal["me", "none"] | None = None,
    source: LeadSource | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sort: Literal["created_at", "updated_at", "next_followup_at", "student_name"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[LeadOut]:
    col = SORTS[sort]
    stmt = _query(status_, owner, source, q, ctx.user_id)
    stmt = stmt.order_by(col.asc().nulls_last() if order == "asc" else col.desc().nulls_last())
    stmt = stmt.order_by(Lead.id).limit(limit)
    return [LeadOut.model_validate(r) for r in await session.scalars(stmt)]


@router.get("/export.csv")
async def export_csv(
    ctx: StaffCtx,
    session: SessionDep,
    status_: Annotated[LeadStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    rows = (
        await session.execute(
            _query(status_, None, None, q, ctx.user_id)
            .add_columns(User.email)
            .outerjoin(User, User.id == Lead.owner_user_id)
            .order_by(Lead.created_at.desc())
            .limit(10_000)
        )
    ).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_FIELDS)
    for lead, owner_email in rows:
        values = {**snapshot(lead, tuple(f for f in CSV_FIELDS if f != "owner"))}
        values["owner"] = owner_email or ""
        # neutralise spreadsheet formulas in user-supplied text (CSV injection)
        writer.writerow(
            [
                ("'" + v) if isinstance(v, str) and v[:1] in "=+-@" else ("" if v is None else v)
                for v in (values[f] for f in CSV_FIELDS)
            ]
        )
    return Response(
        "﻿" + buf.getvalue(),  # BOM → Excel opens Urdu names correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leads.csv"'},
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead(
    body: LeadIn, ctx: StaffCtx, request: Request, session: SessionDep
) -> LeadOut:
    if not (body.student_name or body.guardian_name or body.phone):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name or phone is required")
    lead = Lead(**body.model_dump(exclude={"phone"}), phone=_phone(body.phone), source="manual")
    lead.owner_user_id = ctx.user_id
    session.add(lead)
    await session.flush()
    await session.refresh(lead)
    await audit_ctx(
        session,
        ctx,
        request,
        action="lead.create",
        entity="lead",
        entity_id=lead.id,
        after=snapshot(lead, AUDITED),
    )
    return LeadOut.model_validate(lead)


async def _get(session: SessionDep, lead_id: uuid.UUID) -> Lead:
    lead = await session.scalar(select(Lead).where(Lead.id == lead_id))
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    return lead


@router.get("/{lead_id}")
async def get_lead(lead_id: uuid.UUID, _: StaffCtx, session: SessionDep) -> LeadDetail:
    lead = await _get(session, lead_id)
    owner = await session.get(User, lead.owner_user_id) if lead.owner_user_id else None
    bookings = (
        await session.execute(
            select(Booking, Slot)
            .join(Slot, Slot.id == Booking.slot_id)
            .where(
                or_(
                    Booking.lead_id == lead.id,
                    Booking.contact_id == lead.contact_id if lead.contact_id else false(),
                )
            )
            .order_by(Slot.starts_at.desc())
        )
    ).all()
    convs = (
        list(
            await session.scalars(
                select(Conversation)
                .where(Conversation.contact_id == lead.contact_id)
                .order_by(Conversation.updated_at.desc())
                .limit(10)
            )
        )
        if lead.contact_id
        else []
    )
    audits = await session.scalars(
        select(AuditLog)
        .where(AuditLog.entity == "lead", AuditLog.entity_id == str(lead.id))
        .order_by(AuditLog.created_at.desc())
        .limit(30)
    )
    timeline = [TimelineItem(at=lead.created_at, kind="created", text=f"Lead from {lead.source}")]
    timeline += [
        TimelineItem(
            at=b.created_at,
            kind="booking",
            text=f"{s.kind.capitalize()} booked for {s.starts_at.isoformat()} ({b.status})",
            ref=b.code,
        )
        for b, s in bookings
    ]
    timeline += [
        TimelineItem(at=c.created_at, kind="conversation", text=f"{c.channel} chat", ref=str(c.id))
        for c in convs
    ]
    for a in audits:
        if a.action == "lead.update" and a.before and a.after:
            changed = [k for k in a.after if a.before.get(k) != a.after.get(k)]
            if changed:
                text = ", ".join(f"{k}: {a.before.get(k)} → {a.after.get(k)}" for k in changed)
                timeline.append(TimelineItem(at=a.created_at, kind="audit", text=text))
    timeline.sort(key=lambda t: t.at, reverse=True)
    return LeadDetail(
        **LeadOut.model_validate(lead).model_dump(),
        owner_name=owner.name if owner else None,
        bookings=[
            {
                "id": str(b.id),
                "code": b.code,
                "status": b.status,
                "kind": s.kind,
                "starts_at": s.starts_at.isoformat(),
            }
            for b, s in bookings
        ],
        conversations=[
            {"id": str(c.id), "channel": c.channel, "mode": c.mode, "status": c.status}
            for c in convs
        ],
        timeline=timeline,
    )


@router.patch("/{lead_id}")
async def patch_lead(
    lead_id: uuid.UUID, body: LeadPatch, ctx: StaffCtx, request: Request, session: SessionDep
) -> LeadOut:
    lead = await _get(session, lead_id)
    before = snapshot(lead, AUDITED)
    data = body.model_dump(exclude_unset=True, exclude={"clear_owner"})
    if "phone" in data:
        data["phone"] = _phone(data["phone"])
    if data.get("owner_user_id"):
        ok = await session.scalar(
            select(Membership.id).where(
                Membership.user_id == data["owner_user_id"], Membership.status == "active"
            )
        )
        if ok is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Not an active member")
    if data.get("status") is not None and data["status"] not in LEAD_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown status")
    for key, value in data.items():
        if key == "status" and value is None:
            continue
        setattr(lead, key, value)
    if body.clear_owner:
        lead.owner_user_id = None
    lead.updated_at = dt.datetime.now(dt.UTC)
    await session.flush()
    await audit_ctx(
        session,
        ctx,
        request,
        action="lead.update",
        entity="lead",
        entity_id=lead.id,
        before=before,
        after=snapshot(lead, AUDITED),
    )
    return LeadOut.model_validate(lead)
