"""`/api/v1/institution` — profile, settings and onboarding (PLAN §14 Institution; 5.2, 5.8).

`institutions.settings` layout:
- top-level **string** keys (address, phone, office_hours, …) are the "details" the assistant
  sees in its tenant prompt block → edited as a key/value list ("details");
- dict keys: `widget` (theme, origins, whatsapp_number, welcome), `escalation` (keywords →
  human), `onboarding` (completed steps) — dicts never enter the prompt (see `tenant_view`);
- `cta` (string, skipped by the prompt; the CTA comes from the institution type).
Staff+ read; admin+ write. Every write is audited with before/after."""

import re
import uuid
from typing import Any, Literal
from zoneinfo import available_timezones

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import AdminCtx, SessionDep, SettingsDep, StaffCtx, audit_mutations
from app.core.tenancy import TenantContext
from app.models.core import Institution, Membership
from app.models.facts import FeeItem, KeyDate, Program, Scholarship, TransportRoute
from app.models.kb import Document
from app.services.audit import audit_ctx
from app.services.widget import COLOR_RE, snippet, widget_settings

router = APIRouter(prefix="/institution", tags=["institution"], dependencies=[audit_mutations])
Lang = Literal["en", "ur", "roman_ur"]
STEPS = ("profile", "documents", "facts", "whatsapp", "widget", "done")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DETAIL_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
RESERVED = {"widget", "escalation", "onboarding", "cta", "academic_year"}
ORIGIN = re.compile(r"^https?://[a-z0-9.-]+(:\d{1,5})?$")
PROFILE_FIELDS = ("name", "type", "city", "timezone", "languages", "quiet_hours", "status")


class QuietHours(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not HHMM.match(v):
            raise ValueError("use HH:MM (24h)")
        return v


class InstitutionOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    type: str
    city: str
    timezone: str
    languages: list[str]
    quiet_hours: dict[str, Any]
    status: str
    plan_id: uuid.UUID | None
    wa_phone_number_id: str | None
    facts_version: int


class InstitutionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=200)
    type: Literal["school", "college", "university"] | None = None
    city: str | None = Field(default=None, min_length=2, max_length=80)
    timezone: str | None = None
    languages: list[Lang] | None = Field(default=None, min_length=1)
    quiet_hours: QuietHours | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None and v not in available_timezones():
            raise ValueError("unknown timezone")
        return v


class WidgetSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_color: str | None = None
    position: Literal["left", "right"] | None = None
    allowed_origins: list[str] | None = Field(default=None, max_length=20)
    whatsapp_number: str | None = Field(default=None, max_length=15)
    welcome: dict[Lang, str] | None = None

    @field_validator("primary_color")
    @classmethod
    def _color(cls, v: str | None) -> str | None:
        if v is not None and not COLOR_RE.match(v):
            raise ValueError("use a hex colour like #0f766e")
        return v

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = []
        for o in v:
            norm = o.strip().rstrip("/").lower()
            if not ORIGIN.match(norm):
                raise ValueError(f"not an origin (scheme://host[:port]): {o}")
            out.append(norm)
        return sorted(set(out))

    @field_validator("whatsapp_number")
    @classmethod
    def _wa(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        digits = re.sub(r"\D", "", v)
        if not re.fullmatch(r"92\d{10}", digits):
            raise ValueError("use international format, e.g. 923001234567")
        return digits

    @field_validator("welcome")
    @classmethod
    def _welcome(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is not None and any(len(t) > 300 for t in v.values()):
            raise ValueError("welcome text max 300 characters")
        return v


class EscalationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keywords: list[str] = Field(default_factory=list, max_length=50)
    max_ai_turns: int | None = Field(default=None, ge=1, le=100)

    @field_validator("keywords")
    @classmethod
    def _kw(cls, v: list[str]) -> list[str]:
        out = sorted({k.strip() for k in v if k.strip()})
        if any(len(k) > 40 for k in out):
            raise ValueError("keyword max 40 characters")
        return out


class SettingsOut(BaseModel):
    details: dict[str, str]
    cta: str | None
    widget: dict[str, Any]
    escalation: dict[str, Any]
    snippet: str


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    details: dict[str, str] | None = None  # replaces all detail keys
    widget: WidgetSettings | None = None  # merged
    escalation: EscalationSettings | None = None  # replaced
    cta: str | None = Field(default=None, max_length=40)

    @field_validator("details")
    @classmethod
    def _details(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return v
        if len(v) > 30:
            raise ValueError("max 30 details")
        for k, val in v.items():
            if not DETAIL_KEY.match(k) or k in RESERVED:
                raise ValueError(f"invalid key {k!r} (lowercase letters, digits, _)")
            if len(val) > 300:
                raise ValueError(f"{k}: max 300 characters")
        return {k: val.strip() for k, val in v.items() if val.strip()}


def _inst_out(inst: Institution) -> InstitutionOut:
    return InstitutionOut(
        id=inst.id,
        slug=inst.slug,
        name=inst.name,
        type=inst.type,
        city=inst.city,
        timezone=inst.timezone,
        languages=list(inst.languages or []),
        quiet_hours=dict(inst.quiet_hours or {}),
        status=inst.status,
        plan_id=inst.plan_id,
        wa_phone_number_id=inst.wa_phone_number_id,
        facts_version=inst.facts_version,
    )


def _settings_out(inst: Institution, settings: Any) -> SettingsOut:
    raw = dict(inst.settings or {})
    esc = raw.get("escalation")
    return SettingsOut(
        details={k: str(v) for k, v in raw.items() if k not in RESERVED and isinstance(v, str)},
        cta=raw.get("cta") if isinstance(raw.get("cta"), str) else None,
        widget=widget_settings(inst),
        escalation=dict(esc) if isinstance(esc, dict) else {},
        snippet=snippet(inst.slug, settings),
    )


async def _inst(session: SessionDep, ctx: TenantContext) -> Institution:
    inst = await session.get(Institution, ctx.institution_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Institution not found")
    return inst


def _apply_profile(inst: Institution, body: InstitutionPatch) -> None:
    for key, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(inst, key, value)


@router.get("")
async def get_institution(ctx: StaffCtx, session: SessionDep) -> InstitutionOut:
    return _inst_out(await _inst(session, ctx))


@router.patch("")
async def patch_institution(
    body: InstitutionPatch, ctx: AdminCtx, request: Request, session: SessionDep
) -> InstitutionOut:
    inst = await _inst(session, ctx)
    before = _inst_out(inst).model_dump(mode="json", include=set(PROFILE_FIELDS))
    _apply_profile(inst, body)
    await session.flush()
    after = _inst_out(inst).model_dump(mode="json", include=set(PROFILE_FIELDS))
    await audit_ctx(
        session,
        ctx,
        request,
        action="institution.update",
        entity="institution",
        entity_id=inst.id,
        before=before,
        after=after,
    )
    return _inst_out(inst)


@router.get("/settings")
async def get_settings_(ctx: StaffCtx, session: SessionDep, settings: SettingsDep) -> SettingsOut:
    return _settings_out(await _inst(session, ctx), settings)


def _apply_settings(inst: Institution, body: SettingsPatch) -> None:
    raw = dict(inst.settings or {})
    if body.details is not None:
        raw = {k: v for k, v in raw.items() if k in RESERVED or not isinstance(v, str)}
        raw.update(body.details)
    if body.widget is not None:
        widget = widget_settings(inst)
        for key, value in body.widget.model_dump(exclude_unset=True).items():
            if value is None:
                widget.pop(key, None)
            else:
                widget[key] = value
        raw["widget"] = widget
    if body.escalation is not None:
        old = raw.get("escalation")
        raw["escalation"] = {
            **(old if isinstance(old, dict) else {}),
            **body.escalation.model_dump(),
        }
    if body.cta is not None:
        raw["cta"] = body.cta
    inst.settings = raw
    flag_modified(inst, "settings")


@router.patch("/settings")
async def patch_settings(
    body: SettingsPatch, ctx: AdminCtx, request: Request, session: SessionDep, settings: SettingsDep
) -> SettingsOut:
    inst = await _inst(session, ctx)
    before = dict(inst.settings or {})
    _apply_settings(inst, body)
    await session.flush()
    await audit_ctx(
        session,
        ctx,
        request,
        action="institution.settings",
        entity="institution",
        entity_id=inst.id,
        before=before,
        after=dict(inst.settings),
    )
    return _settings_out(inst, settings)


# ---- onboarding (5.2) -------------------------------------------------------------------------

FACT_MODELS = (FeeItem, Program, KeyDate, Scholarship, TransportRoute)


class OnboardingOut(BaseModel):
    completed: list[str]
    current: str
    checklist: dict[str, Any]


class OnboardingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: InstitutionPatch | None = None
    widget: WidgetSettings | None = None


async def _onboarding(session: SessionDep, inst: Institution) -> OnboardingOut:
    raw = (inst.settings or {}).get("onboarding")
    completed = [s for s in (raw or {}).get("completed", []) if s in STEPS]
    docs = (
        await session.execute(select(Document.status, func.count()).group_by(Document.status))
    ).all()
    by_status = {s: n for s, n in docs}
    pending = approved = 0
    for model in FACT_MODELS:
        rows = (
            await session.execute(select(model.status, func.count()).group_by(model.status))
        ).all()
        counts = dict(rows)
        pending += counts.get("pending", 0)
        approved += counts.get("approved", 0)
    members = await session.scalar(
        select(func.count()).select_from(Membership).where(Membership.status != "disabled")
    )
    w = widget_settings(inst)
    checklist = {
        "profile": bool(inst.name and inst.city and inst.languages),
        "documents_total": sum(n for s, n in by_status.items() if s != "superseded"),
        "documents_ready": by_status.get("ready", 0),
        "documents_failed": by_status.get("failed", 0),
        "facts_pending": pending,
        "facts_approved": approved,
        "whatsapp_connected": bool(inst.wa_phone_number_id),
        "widget_origins": len(w.get("allowed_origins", [])),
        "team_members": members or 0,
    }
    current = next((s for s in STEPS if s not in completed), "done")
    return OnboardingOut(completed=completed, current=current, checklist=checklist)


@router.get("/onboarding")
async def get_onboarding(ctx: StaffCtx, session: SessionDep) -> OnboardingOut:
    return await _onboarding(session, await _inst(session, ctx))


@router.post("/onboarding/{step}")
async def complete_onboarding_step(
    step: Literal["profile", "documents", "facts", "whatsapp", "widget", "done"],
    body: OnboardingIn,
    ctx: AdminCtx,
    request: Request,
    session: SessionDep,
) -> OnboardingOut:
    """Mark a wizard step done (resume = first step not in `completed`). `profile` / `widget`
    steps may carry their form data so the wizard saves and advances in one call."""
    inst = await _inst(session, ctx)
    if step == "profile" and body.profile is not None:
        _apply_profile(inst, body.profile)
    if step == "widget" and body.widget is not None:
        _apply_settings(inst, SettingsPatch(widget=body.widget))
    raw = dict(inst.settings or {})
    ob = dict(raw.get("onboarding") or {})
    done = list(dict.fromkeys([*ob.get("completed", []), step]))
    raw["onboarding"] = {**ob, "completed": done}
    inst.settings = raw
    flag_modified(inst, "settings")
    await session.flush()
    await audit_ctx(
        session,
        ctx,
        request,
        action="institution.onboarding",
        entity="institution",
        entity_id=inst.id,
        after={"step": step, "completed": done},
    )
    return await _onboarding(session, inst)
