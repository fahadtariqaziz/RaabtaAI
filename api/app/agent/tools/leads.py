"""Lead capture, follow-ups and contact preferences (PLAN §9.3). Deterministic code: the model
only passes what the contact said; phones are normalized here, dates validated here."""

import datetime as dt
import re
import uuid
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import ToolContext, ToolError, ToolRuntime
from app.models.conversations import Contact, Conversation, Followup, Lead

FOLLOWUP_MAX_DAYS = 90
FOLLOWUP_HOUR = 10


def normalize_pk_phone(raw: str | None) -> str | None:
    """Pakistani mobile/landline → E.164 (`+923001234567`); None if it can't be a PK number."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0092"):
        digits = digits[4:]
    elif digits.startswith("92"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if re.fullmatch(r"3\d{9}", digits) or re.fullmatch(r"[2-9]\d{8,9}", digits):
        return f"+92{digits}"
    return None


def local_now(ctx: ToolContext) -> dt.datetime:
    return ctx.now.astimezone(ZoneInfo(ctx.timezone))


async def upsert_lead(
    session: AsyncSession,
    ctx: ToolContext | None = None,
    *,
    contact_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    channel: str | None = None,
    phone: str | None,
    student_name: str | None = None,
    guardian_name: str | None = None,
    interest: str | None = None,
    notes: str | None = None,
    status: str | None = None,
) -> Lead:
    """Dedupe by phone within the institution, else the contact's latest lead; links the
    conversation and fills empty contact fields. Never overwrites a value with null.
    Pass a `ToolContext` (tools) or explicit ids (summarizer)."""
    if ctx is not None:
        contact_id, conversation_id, channel = ctx.contact_id, ctx.conversation_id, ctx.channel
    if contact_id is None or conversation_id is None or channel is None:
        raise ValueError("upsert_lead needs a ToolContext or contact/conversation/channel")
    lead = None
    if phone:
        lead = await session.scalar(select(Lead).where(Lead.phone == phone).limit(1))
    if lead is None:
        lead = await session.scalar(
            select(Lead)
            .where(Lead.contact_id == contact_id)
            .order_by(Lead.created_at.desc())
            .limit(1)
        )
    if lead is None:
        lead = Lead(contact_id=contact_id, source=channel, status="new")
        session.add(lead)
    for attr, value in (
        ("phone", phone),
        ("student_name", student_name),
        ("guardian_name", guardian_name),
        ("interest", interest),
    ):
        if value:
            setattr(lead, attr, value.strip())
    if notes:
        lead.notes = f"{lead.notes}\n{notes}".strip() if lead.notes else notes.strip()
    if lead.contact_id is None:
        lead.contact_id = contact_id
    if status == "visit_booked" and lead.status in (None, "new", "contacted"):
        lead.status = "visit_booked"
    await session.flush()
    conv = await session.get(Conversation, conversation_id)
    if conv is not None and conv.lead_id is None:
        conv.lead_id = lead.id
    contact = await session.get(Contact, contact_id)
    if contact is not None:
        if phone and not contact.phone:
            contact.phone = phone
        if guardian_name and not contact.name:
            contact.name = guardian_name.strip()
    return lead


class SaveLeadInput(BaseModel):
    student_name: str | None = Field(max_length=120, description="Student's name if given")
    guardian_name: str | None = Field(max_length=120, description="Parent/guardian name if given")
    phone: str | None = Field(max_length=32, description="Phone exactly as the contact typed it")
    interest: str = Field(
        min_length=1, max_length=200, description="Class/program of interest, e.g. 'Class 3'"
    )
    notes: str | None = Field(max_length=500, description="Short context for the office")


class SaveLeadOutput(BaseModel):
    lead_id: str
    saved: list[str]
    missing_fields: list[str]


async def save_lead(
    args: SaveLeadInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> SaveLeadOutput:
    phone = normalize_pk_phone(args.phone)
    if args.phone and phone is None:
        raise ToolError(
            "That phone number doesn't look like a valid Pakistani number. Ask the contact to "
            "re-check it (e.g. 0300-1234567). Nothing was saved."
        )
    lead = await upsert_lead(
        session,
        ctx,
        phone=phone,
        student_name=args.student_name,
        guardian_name=args.guardian_name,
        interest=args.interest,
        notes=args.notes,
    )
    values = {
        "student_name": lead.student_name,
        "guardian_name": lead.guardian_name,
        "phone": lead.phone,
        "interest": lead.interest,
    }
    ctx.events.append({"type": "lead_saved", "lead_id": str(lead.id), "has_phone": bool(phone)})
    return SaveLeadOutput(
        lead_id=str(lead.id),
        saved=sorted(k for k, v in values.items() if v),
        missing_fields=sorted(k for k, v in values.items() if not v),
    )


class FollowupInput(BaseModel):
    when: dt.date = Field(description="Date the contact agreed to be contacted (YYYY-MM-DD)")
    reason: str = Field(min_length=1, max_length=200, description="Why, in a few words")


class FollowupOutput(BaseModel):
    followup_id: str
    scheduled_for: str


async def schedule_followup(
    args: FollowupInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> FollowupOutput:
    today = local_now(ctx).date()
    if args.when <= today:
        raise ToolError(f"The follow-up date must be after today ({today.isoformat()}).")
    if args.when > today + dt.timedelta(days=FOLLOWUP_MAX_DAYS):
        raise ToolError(f"Follow-ups can be scheduled at most {FOLLOWUP_MAX_DAYS} days ahead.")
    conv = await session.get(Conversation, ctx.conversation_id)
    due = dt.datetime.combine(args.when, dt.time(FOLLOWUP_HOUR), tzinfo=ZoneInfo(ctx.timezone))
    followup = Followup(
        contact_id=ctx.contact_id,
        lead_id=conv.lead_id if conv else None,
        due_at=due,
        kind="lead_followup",
    )
    session.add(followup)
    await session.flush()
    ctx.events.append({"type": "followup_scheduled", "when": args.when.isoformat()})
    return FollowupOutput(
        followup_id=str(followup.id), scheduled_for=due.strftime("%a %d %b %Y, %I:%M %p")
    )


class LanguageInput(BaseModel):
    language: Literal["en", "ur", "roman_ur"]


class AckOutput(BaseModel):
    ok: bool
    message: str


async def set_contact_language(
    args: LanguageInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> AckOutput:
    contact = await session.get(Contact, ctx.contact_id)
    if contact is None:
        raise ToolError("Contact not found.")
    contact.preferred_language = args.language
    return AckOutput(ok=True, message=f"Preferred language set to {args.language}.")


class HandoffInput(BaseModel):
    reason: Literal[
        "human_requested",
        "complaint",
        "fee_dispute",
        "hardship",
        "cannot_answer",
        "booking_change",
        "verification_failed",
        "fee_module_unavailable",
        "other",
    ]
    summary: str = Field(max_length=500, description="2-3 sentences for the staff member")
    urgency: Literal["low", "normal", "high"]


async def handoff_to_human(
    args: HandoffInput, ctx: ToolContext, session: AsyncSession, runtime: ToolRuntime
) -> AckOutput:
    ctx.events.append(
        {"type": "handoff", "reason": args.reason, "summary": args.summary, "urgency": args.urgency}
    )
    return AckOutput(
        ok=True,
        message="Handed off. Tell the contact a colleague from the office will reply in this "
        "chat soon. Do not promise a time.",
    )
