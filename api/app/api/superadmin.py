"""`/api/v1/superadmin/*` — platform tenant management (PLAN §14 Superadmin; step 5.9).

Superadmin only; the session runs as `app_admin` (explicit RLS bypass, `require_superadmin`).
Impersonation = a time-boxed Redis grant (`imp:{user}:{institution}`, 1 h) that lets the
superadmin pass `get_tenant` for that institution with role owner; start/stop are audited in the
target institution's audit log and the admin UI shows a banner while it is active."""

import datetime as dt
import re
import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select, text

from app.api.deps import (
    IMPERSONATION_TTL,
    RedisDep,
    SessionDep,
    SettingsDep,
    SuperAdmin,
    impersonation_key,
)
from app.models.core import Institution, Membership, Plan, User
from app.services import provisioning
from app.services.audit import audit
from app.services.members import invite_url_for

router = APIRouter(prefix="/superadmin", tags=["superadmin"])
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    price_pkr: int | None
    monthly_conversations: int
    monthly_template_sends: int
    monthly_ai_budget_usd: Decimal
    seats: int


class TenantRow(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    type: str
    city: str
    status: str
    plan_id: uuid.UUID | None
    plan_name: str | None
    created_at: dt.datetime
    members: int
    conversations_30d: int
    ai_cost_30d_usd: Decimal
    last_activity_at: dt.datetime | None


class TenantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    name: str = Field(min_length=2, max_length=200)
    type: Literal["school", "college", "university"]
    city: str = Field(min_length=2, max_length=80)
    plan_id: uuid.UUID | None = None
    owner_email: EmailStr
    owner_name: str = Field(min_length=1, max_length=120)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not SLUG.match(v):
            raise ValueError("slug: 3–63 chars, lowercase letters, digits, dashes")
        return v


class TenantPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["trial", "active", "suspended"] | None = None
    plan_id: uuid.UUID | None = None
    clear_plan: bool = False


_TENANTS_SQL = text(
    """
SELECT i.id, i.slug, i.name, i.type, i.city, i.status, i.plan_id, p.name AS plan_name,
       i.created_at,
       (SELECT count(*) FROM memberships m WHERE m.institution_id = i.id
          AND m.status <> 'disabled') AS members,
       (SELECT count(*) FROM conversations c WHERE c.institution_id = i.id
          AND c.created_at > now() - interval '30 days') AS conversations_30d,
       (SELECT coalesce(sum(r.cost_usd), 0) FROM llm_runs r WHERE r.institution_id = i.id
          AND r.created_at > now() - interval '30 days') AS ai_cost_30d_usd,
       (SELECT max(m.created_at) FROM messages m WHERE m.institution_id = i.id) AS last_activity_at
FROM institutions i LEFT JOIN plans p ON p.id = i.plan_id
ORDER BY i.created_at DESC
"""
)


@router.get("/plans")
async def list_plans(_: SuperAdmin, session: SessionDep) -> list[PlanOut]:
    rows = await session.scalars(select(Plan).order_by(Plan.monthly_conversations))
    return [PlanOut.model_validate(p) for p in rows]


@router.get("/institutions")
async def list_institutions(_: SuperAdmin, session: SessionDep) -> list[TenantRow]:
    return [TenantRow(**r) for r in (await session.execute(_TENANTS_SQL)).mappings()]


@router.post("/institutions", status_code=status.HTTP_201_CREATED)
async def create_institution(
    body: TenantIn, user: SuperAdmin, request: Request, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """New tenant (status trial) + an owner invitation link (D-14: no email provider)."""
    if await session.scalar(select(Institution.id).where(Institution.slug == body.slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already taken")
    if body.plan_id and await session.get(Plan, body.plan_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown plan")
    inst = await provisioning.upsert_institution(
        session,
        slug=body.slug,
        name=body.name,
        type=body.type,
        city=body.city,
        plan_id=body.plan_id,
        status="trial",
    )
    owner = await session.scalar(select(User).where(User.email == str(body.owner_email).lower()))
    if owner is None:
        owner = await provisioning.upsert_user(
            session, email=str(body.owner_email), name=body.owner_name
        )
    membership = await provisioning.upsert_membership(
        session,
        institution_id=inst.id,
        user_id=owner.id,
        role="owner",
        status="active" if owner.password_hash else "invited",
    )
    invite_url = None
    if membership.status == "invited":
        invite_url = await invite_url_for(session, membership, user.id, settings)
    await audit(
        session,
        institution_id=inst.id,
        actor_user_id=user.id,
        action="superadmin.create_tenant",
        entity="institution",
        entity_id=inst.id,
        after={"slug": inst.slug, "owner": owner.email, "plan_id": body.plan_id},
        request=request,
    )
    return {"id": str(inst.id), "slug": inst.slug, "owner_invite_url": invite_url}


@router.patch("/institutions/{institution_id}")
async def patch_institution(
    institution_id: uuid.UUID,
    body: TenantPatch,
    user: SuperAdmin,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    inst = await session.get(Institution, institution_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Institution not found")
    before = {"status": inst.status, "plan_id": inst.plan_id}
    if body.status:
        inst.status = body.status
    if body.clear_plan:
        inst.plan_id = None
    elif body.plan_id:
        if await session.get(Plan, body.plan_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown plan")
        inst.plan_id = body.plan_id
    await session.flush()
    after = {"status": inst.status, "plan_id": inst.plan_id}
    await audit(
        session,
        institution_id=inst.id,
        actor_user_id=user.id,
        action="superadmin.update_tenant",
        entity="institution",
        entity_id=inst.id,
        before=before,
        after=after,
        request=request,
    )
    return {"id": str(inst.id), **{k: (str(v) if v else v) for k, v in after.items()}}


@router.post("/impersonate/{institution_id}")
async def impersonate(
    institution_id: uuid.UUID,
    user: SuperAdmin,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
) -> dict[str, Any]:
    inst = await session.get(Institution, institution_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Institution not found")
    await redis.set(impersonation_key(user.id, inst.id), "1", ex=IMPERSONATION_TTL)
    await audit(
        session,
        institution_id=inst.id,
        actor_user_id=user.id,
        action="superadmin.impersonate",
        entity="institution",
        entity_id=inst.id,
        after={"ttl_s": IMPERSONATION_TTL},
        request=request,
    )
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=IMPERSONATION_TTL)
    return {
        "institution_id": str(inst.id),
        "institution_name": inst.name,
        "institution_slug": inst.slug,
        "expires_at": expires.isoformat(),
    }


@router.delete("/impersonate/{institution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_impersonating(
    institution_id: uuid.UUID,
    user: SuperAdmin,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
) -> None:
    inst = await session.get(Institution, institution_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Institution not found")
    await redis.delete(impersonation_key(user.id, inst.id))
    await audit(
        session,
        institution_id=inst.id,
        actor_user_id=user.id,
        action="superadmin.impersonate_end",
        entity="institution",
        entity_id=inst.id,
        request=request,
    )


@router.get("/usage")
async def global_usage(_: SuperAdmin, session: SessionDep, days: int = 30) -> dict[str, Any]:
    days = max(1, min(days, 366))
    rows = (
        (
            await session.execute(
                text(
                    """SELECT date_trunc('day', created_at)::date AS date, count(*) AS runs,
                   coalesce(sum(cost_usd), 0) AS cost_usd,
                   coalesce(sum(input_tokens + cache_read_tokens + cache_write_tokens), 0)
                     AS tokens_in,
                   coalesce(sum(output_tokens), 0) AS tokens_out
                   FROM llm_runs WHERE created_at > now() - make_interval(days => :d)
                   GROUP BY 1 ORDER BY 1"""
                ),
                {"d": days},
            )
        )
        .mappings()
        .all()
    )
    tenants = await session.scalar(select(func.count()).select_from(Institution))
    users = await session.scalar(
        select(func.count(func.distinct(Membership.user_id))).where(Membership.status == "active")
    )
    total = sum((Decimal(r["cost_usd"]) for r in rows), Decimal(0))
    return {
        "days": [dict(r) for r in rows],
        "totals": {"tenants": tenants or 0, "active_users": users or 0, "cost_usd": total},
    }
