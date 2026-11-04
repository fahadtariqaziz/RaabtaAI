"""Institution members: list, invite, change role/status, remove (PLAN §14 Members).

Runs on a tenant-scoped session (RLS + ORM filter). Rules:
- admin+ manages members; only an owner may grant, change or remove the owner role.
- an institution always keeps at least one active owner.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import new_opaque_token, token_hash
from app.core.tenancy import TenantContext
from app.models.core import Membership, User
from app.schemas.auth import InviteIn, InviteOut, MemberOut, MemberPatch
from app.services.audit import audit_ctx, snapshot

_FIELDS = ("role", "status")


class MemberError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _out(m: Membership, u: User) -> MemberOut:
    return MemberOut(
        id=m.id,
        user_id=u.id,
        email=u.email,
        name=u.name,
        role=m.role,
        status=m.status,
        created_at=m.created_at,
    )


async def list_members(session: AsyncSession) -> list[MemberOut]:
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .order_by(Membership.created_at)
    )
    return [_out(m, u) for m, u in rows.all()]


async def _get(session: AsyncSession, member_id: uuid.UUID) -> tuple[Membership, User]:
    row = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.id == member_id)
        )
    ).first()
    if row is None:
        raise MemberError(404, "Member not found")
    return (row[0], row[1])


async def _active_owner_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.role == "owner", Membership.status == "active")
        )
        or 0
    )


async def invite(
    session: AsyncSession,
    ctx: TenantContext,
    request: Request,
    body: InviteIn,
    settings: Settings,
) -> InviteOut:
    if body.role == "owner" and ctx.role != "owner":
        raise MemberError(403, "Only an owner can invite an owner")
    user = await session.scalar(select(User).where(User.email == body.email))
    if user is None:
        user = User(email=body.email, name=body.name)
        session.add(user)
        await session.flush()
    elif await session.scalar(select(Membership.id).where(Membership.user_id == user.id)):
        raise MemberError(409, "This person is already a member or invited")
    token = new_opaque_token()
    expires = datetime.now(UTC) + timedelta(days=settings.invite_ttl_days)
    membership = Membership(
        institution_id=ctx.institution_id,
        user_id=user.id,
        role=body.role,
        status="invited",
        invited_by=ctx.user_id,
        invite_token_hash=token_hash(token),
        invite_expires_at=expires,
    )
    session.add(membership)
    await session.flush()
    await session.refresh(membership)
    await audit_ctx(
        session,
        ctx,
        request,
        action="member.invited",
        entity="membership",
        entity_id=membership.id,
        after={**snapshot(membership, _FIELDS), "email": user.email},
    )
    return InviteOut(
        member=_out(membership, user),
        invite_url=f"{settings.admin_base_url.rstrip('/')}/invite/accept#token={token}",
        invite_expires_at=expires,
    )


async def update(
    session: AsyncSession,
    ctx: TenantContext,
    request: Request,
    member_id: uuid.UUID,
    body: MemberPatch,
) -> MemberOut:
    membership, user = await _get(session, member_id)
    touches_owner = membership.role == "owner" or body.role == "owner"
    if touches_owner and ctx.role != "owner":
        raise MemberError(403, "Only an owner can change an owner's membership")
    if body.status == "active" and membership.status == "invited":
        raise MemberError(409, "Invited members become active by accepting the invitation")
    before = snapshot(membership, _FIELDS)
    if body.role is not None:
        membership.role = body.role
    if body.status is not None:
        membership.status = body.status
    await session.flush()
    was_active_owner = before["role"] == "owner" and before["status"] == "active"
    if was_active_owner and await _active_owner_count(session) == 0:
        raise MemberError(409, "An institution needs at least one active owner")
    await audit_ctx(
        session,
        ctx,
        request,
        action="member.updated",
        entity="membership",
        entity_id=membership.id,
        before=before,
        after=snapshot(membership, _FIELDS),
    )
    return _out(membership, user)


async def remove(
    session: AsyncSession, ctx: TenantContext, request: Request, member_id: uuid.UUID
) -> None:
    membership, user = await _get(session, member_id)
    if membership.role == "owner" and ctx.role != "owner":
        raise MemberError(403, "Only an owner can remove an owner")
    before = {**snapshot(membership, _FIELDS), "email": user.email}
    await session.delete(membership)
    await session.flush()
    if before["role"] == "owner" and await _active_owner_count(session) == 0:
        raise MemberError(409, "An institution needs at least one active owner")
    await audit_ctx(
        session,
        ctx,
        request,
        action="member.removed",
        entity="membership",
        entity_id=member_id,
        before=before,
    )


async def invite_url_for(
    session: AsyncSession, membership: Membership, invited_by: uuid.UUID, settings: Settings
) -> str:
    """(Re)issue a one-time invite token for an existing `invited` membership (superadmin
    tenant creation); returns the shareable accept link."""
    token = new_opaque_token()
    membership.invited_by = invited_by
    membership.invite_token_hash = token_hash(token)
    membership.invite_expires_at = datetime.now(UTC) + timedelta(days=settings.invite_ttl_days)
    await session.flush()
    return f"{settings.admin_base_url.rstrip('/')}/invite/accept#token={token}"
