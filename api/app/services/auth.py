"""Login, token issuing, invitation acceptance (PLAN §4 Auth, §18).

Cross-institution lookups (a user's memberships, an invitation by token) run with
`scope_to_admin` — the user has no active institution yet at that point.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    hash_password,
    needs_rehash,
    token_hash,
    validate_password,
    verify_password,
)
from app.core.tenancy import scope_to_admin
from app.models.core import Institution, Membership, User
from app.schemas.auth import MembershipOut, MeOut, UserOut
from app.services.audit import audit, snapshot
from app.services.auth_tokens import LoginLockout, RefreshTokenStore


class AuthError(Exception):
    """Generic auth failure; message is safe to return."""


class LockedOutError(AuthError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many failed logins; try again later")
        self.retry_after = retry_after


class InviteError(AuthError):
    pass


@dataclass(frozen=True)
class Session:
    access_token: str
    expires_in: int
    refresh_token: str
    me: MeOut


async def memberships_for(session: AsyncSession, user_id: uuid.UUID) -> list[MembershipOut]:
    """Active memberships across institutions (admin scope; caller must already be the user)."""
    await scope_to_admin(session)
    rows = await session.execute(
        select(Membership, Institution)
        .join(Institution, Institution.id == Membership.institution_id)
        .where(
            Membership.user_id == user_id,
            Membership.status == "active",
            Institution.status != "suspended",
        )
        .order_by(Institution.name)
    )
    return [
        MembershipOut(
            membership_id=m.id,
            institution_id=i.id,
            institution_name=i.name,
            institution_slug=i.slug,
            role=m.role,
        )
        for m, i in rows.all()
    ]


async def me(session: AsyncSession, user: User) -> MeOut:
    return MeOut(
        user=UserOut.model_validate(user), memberships=await memberships_for(session, user.id)
    )


async def issue_session(
    session: AsyncSession,
    user: User,
    settings: Settings,
    refresh: RefreshTokenStore,
    *,
    family: str | None = None,
    refresh_token: str | None = None,
) -> Session:
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    access = create_access_token(user.id, secret=settings.jwt_secret.get_secret_value(), ttl=ttl)
    if refresh_token is None:
        refresh_token = (await refresh.issue(user.id, family)).token
    return Session(
        access_token=access,
        expires_in=int(ttl.total_seconds()),
        refresh_token=refresh_token,
        me=await me(session, user),
    )


async def login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    settings: Settings,
    lockout: LoginLockout,
    refresh: RefreshTokenStore,
) -> Session:
    retry = await lockout.retry_after(email)
    if retry is not None:
        raise LockedOutError(retry)
    user = await session.scalar(select(User).where(User.email == email))
    ok = verify_password(user.password_hash if user else None, password)
    if user is None or not ok or not user.is_active:
        await lockout.record_failure(email)
        raise AuthError("Invalid email or password")
    await lockout.reset(email)
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    return await issue_session(session, user, settings, refresh)


async def refresh_session(
    session: AsyncSession, *, token: str, settings: Settings, refresh: RefreshTokenStore
) -> Session:
    issued = await refresh.rotate(token)  # raises RefreshTokenError
    user = await session.get(User, issued.user_id)
    if user is None or not user.is_active:
        await refresh.revoke(issued.token)
        raise AuthError("Account disabled")
    return await issue_session(session, user, settings, refresh, refresh_token=issued.token)


async def accept_invitation(
    session: AsyncSession,
    *,
    token: str,
    password: str,
    name: str | None,
    settings: Settings,
    refresh: RefreshTokenStore,
    ip: str | None,
) -> Session:
    await scope_to_admin(session)
    membership = await session.scalar(
        select(Membership).where(Membership.invite_token_hash == token_hash(token))
    )
    now = datetime.now(UTC)
    if (
        membership is None
        or membership.status != "invited"
        or membership.invite_expires_at is None
        or membership.invite_expires_at < now
    ):
        raise InviteError("Invitation is invalid or has expired")
    user = await session.get(User, membership.user_id)
    if user is None or not user.is_active:
        raise InviteError("Invitation is invalid or has expired")
    if user.password_hash is None:
        validate_password(password, email=user.email)  # PasswordPolicyError → 422
        user.password_hash = hash_password(password)
    elif not verify_password(user.password_hash, password):
        # Existing account (member elsewhere): prove it is theirs with the current password.
        raise InviteError("Use your existing password to accept this invitation")
    if name:
        user.name = name
    before = snapshot(membership, ("status",))
    membership.status = "active"
    membership.invite_token_hash = None
    membership.invite_expires_at = None
    await audit(
        session,
        institution_id=membership.institution_id,
        actor_user_id=user.id,
        action="member.invite_accepted",
        entity="membership",
        entity_id=membership.id,
        before=before,
        after=snapshot(membership, ("status", "role")),
        ip=ip,
    )
    await session.flush()
    return await issue_session(session, user, settings, refresh)
