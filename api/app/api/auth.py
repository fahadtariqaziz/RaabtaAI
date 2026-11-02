"""`/api/v1/auth/*` — login, refresh (rotating httpOnly cookie), logout, me, invitation accept."""

from typing import Annotated, Any

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, RedisDep, SessionDep, SettingsDep, client_ip
from app.core.config import Settings
from app.core.security import PasswordPolicyError
from app.schemas.auth import AcceptInviteIn, LoginIn, MeOut, TokenOut
from app.services import auth as svc
from app.services.auth_tokens import LoginLockout, RefreshTokenError, RefreshTokenStore

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "raabta_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _stores(redis: RedisDep, settings: Settings) -> tuple[LoginLockout, RefreshTokenStore]:
    return (
        LoginLockout(
            redis, settings.login_lockout_threshold, settings.login_lockout_window_seconds
        ),
        RefreshTokenStore(redis, settings.refresh_token_ttl_days * 86400),
    )


def _respond(response: Response, sess: svc.Session, settings: Settings) -> TokenOut:
    response.set_cookie(
        REFRESH_COOKIE,
        sess.refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.env == "prod",
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenOut(
        access_token=sess.access_token,
        expires_in=sess.expires_in,
        user=sess.me.user,
        memberships=sess.me.memberships,
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.post("/login")
async def login(
    body: LoginIn,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> TokenOut:
    lockout, refresh = _stores(redis, settings)
    try:
        sess = await svc.login(
            session,
            email=body.email,
            password=body.password,
            settings=settings,
            lockout=lockout,
            refresh=refresh,
        )
    except svc.LockedOutError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from None
    except svc.AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
    return _respond(response, sess, settings)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
    raabta_rt: Annotated[str | None, Cookie()] = None,
) -> Any:
    expired = JSONResponse({"detail": "Session expired"}, status.HTTP_401_UNAUTHORIZED)
    _clear_cookie(expired)
    if not raabta_rt:
        return expired
    _, store = _stores(redis, settings)
    try:
        sess = await svc.refresh_session(session, token=raabta_rt, settings=settings, refresh=store)
    except (RefreshTokenError, svc.AuthError):
        return expired
    return _respond(response, sess, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    settings: SettingsDep,
    redis: RedisDep,
    raabta_rt: Annotated[str | None, Cookie()] = None,
) -> None:
    if raabta_rt:
        _, store = _stores(redis, settings)
        await store.revoke(raabta_rt)
    _clear_cookie(response)


@router.get("/me")
async def get_me(user: CurrentUser, session: SessionDep) -> MeOut:
    return await svc.me(session, user)


@router.post("/invitations/accept")
async def accept_invitation(
    body: AcceptInviteIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> TokenOut:
    _, store = _stores(redis, settings)
    try:
        sess = await svc.accept_invitation(
            session,
            token=body.token,
            password=body.password,
            name=body.name,
            settings=settings,
            refresh=store,
            ip=client_ip(request),
        )
    except PasswordPolicyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except svc.InviteError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return _respond(response, sess, settings)
