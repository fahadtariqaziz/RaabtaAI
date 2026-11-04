"""Shared FastAPI dependencies: DB session, current user, tenant context, RBAC (PLAN §18).

Route pattern:
    @router.get("/things")
    async def list_things(ctx: Annotated[TenantContext, Depends(require_role("staff"))],
                          session: SessionDep) -> ...

`require_role(min_role)` resolves the user from the bearer JWT, reads `X-Institution`, scopes the
request's DB session to that institution (RLS role + GUC + ORM filter) and checks an active
membership with at least `min_role`. Roles rank owner > admin > staff.
"""

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from arq.connections import ArqRedis
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp.client import WhatsAppClient
from app.core.config import Settings
from app.core.security import TokenError, decode_access_token
from app.core.tenancy import TenantContext, scope_to_admin, scope_to_tenant
from app.db.session import get_session
from app.kb.blobstore import BlobStore
from app.models.core import Membership, User
from app.services.audit import MUTATING, audit

# scope="function": commit happens before the response is sent (a failed commit → 500, not 200).
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]

ROLE_RANK = {"staff": 1, "admin": 2, "owner": 3}
_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_redis(request: Request) -> ArqRedis:
    redis: ArqRedis = request.app.state.resources.redis
    return redis


def get_blobstore(request: Request) -> BlobStore:
    store: BlobStore = request.app.state.resources.blobstore
    return store


def get_wa_client(request: Request) -> WhatsAppClient | None:
    """Process-wide Graph API client (None until META_ACCESS_TOKEN is set). Tests inject
    `app.state.wa_client` (httpx.MockTransport)."""
    state = request.app.state
    if getattr(state, "wa_client", None) is None and state.settings.meta_access_token is not None:
        state.wa_client = WhatsAppClient.from_settings(state.settings)
    return getattr(state, "wa_client", None)


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
WaClientDep = Annotated[WhatsAppClient | None, Depends(get_wa_client)]
RedisDep = Annotated[ArqRedis, Depends(get_redis)]
BlobStoreDep = Annotated[BlobStore, Depends(get_blobstore)]


IMPERSONATION_TTL = 3600


def impersonation_key(user_id: uuid.UUID, institution_id: uuid.UUID) -> str:
    return f"imp:{user_id}:{institution_id}"


async def impersonating(redis: ArqRedis, user_id: uuid.UUID, institution_id: uuid.UUID) -> bool:
    return bool(await redis.exists(impersonation_key(user_id, institution_id)))


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if creds is None:
        raise _unauthorized()
    try:
        user_id = decode_access_token(
            creds.credentials, secret=settings.jwt_secret.get_secret_value()
        )
    except TokenError:
        raise _unauthorized("Invalid or expired token") from None
    user = await session.get(User, user_id)  # `users` is global (no RLS)
    if user is None or not user.is_active:
        raise _unauthorized("Invalid or expired token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _parse_institution(value: str | None) -> uuid.UUID:
    if not value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Institution header is required")
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Institution must be a UUID") from None


async def get_tenant(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    x_institution: Annotated[str | None, Header()] = None,
) -> TenantContext:
    institution_id = _parse_institution(x_institution)
    await scope_to_tenant(session, institution_id)
    membership = await session.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.status == "active")
    )
    if membership is None:
        # Superadmin impersonation (5.9): explicit, audited, time-boxed grant in Redis.
        if user.is_superadmin and await impersonating(
            request.app.state.resources.redis, user.id, institution_id
        ):
            ctx = TenantContext(
                institution_id=institution_id, user_id=user.id, role="owner", membership_id=None
            )
            request.state.tenant = ctx
            return ctx
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this institution")
    ctx = TenantContext(
        institution_id=institution_id,
        user_id=user.id,
        role=membership.role,
        membership_id=membership.id,
    )
    request.state.tenant = ctx
    return ctx


TenantDep = Annotated[TenantContext, Depends(get_tenant)]


def require_role(
    min_role: str,
) -> Callable[[TenantContext], Coroutine[Any, Any, TenantContext]]:
    if min_role not in ROLE_RANK:
        raise ValueError(f"unknown role {min_role!r}")

    async def _check(ctx: TenantDep) -> TenantContext:
        if ROLE_RANK[ctx.role] < ROLE_RANK[min_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role {min_role} or higher")
        return ctx

    _check.__name__ = f"require_role_{min_role}"
    return _check


StaffCtx = Annotated[TenantContext, Depends(require_role("staff"))]
AdminCtx = Annotated[TenantContext, Depends(require_role("admin"))]
OwnerCtx = Annotated[TenantContext, Depends(require_role("owner"))]


async def require_superadmin(session: SessionDep, user: CurrentUser) -> User:
    """Platform routes: superadmin only; session runs as `app_admin` (RLS bypass, explicit)."""
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Superadmin only")
    await scope_to_admin(session)
    return user


SuperAdmin = Annotated[User, Depends(require_superadmin)]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _audit_mutations(
    request: Request, session: SessionDep, ctx: TenantDep
) -> AsyncIterator[None]:
    request.state.audited = False
    yield  # an exception from the handler propagates: nothing committed, nothing audited
    if request.method in MUTATING and not request.state.audited:
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        await audit(
            session,
            institution_id=ctx.institution_id,
            actor_user_id=ctx.user_id,
            action=f"{request.method} {path}",
            entity="http",
            entity_id=None,
            after={"path_params": dict(request.path_params)},
            request=request,
        )
        await session.flush()


audit_mutations = Depends(_audit_mutations, scope="function")
