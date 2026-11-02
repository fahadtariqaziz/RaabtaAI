"""`/api/v1/members` — institution members and invitations (admin+ to change, staff+ to view)."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import AdminCtx, SessionDep, SettingsDep, StaffCtx, audit_mutations
from app.schemas.auth import InviteIn, InviteOut, MemberOut, MemberPatch
from app.services import members as svc

router = APIRouter(prefix="/members", tags=["members"], dependencies=[audit_mutations])


def _http(exc: svc.MemberError) -> HTTPException:
    return HTTPException(exc.status_code, exc.detail)


@router.get("")
async def list_members(_: StaffCtx, session: SessionDep) -> list[MemberOut]:
    return await svc.list_members(session)


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_member(
    body: InviteIn, ctx: AdminCtx, request: Request, session: SessionDep, settings: SettingsDep
) -> InviteOut:
    try:
        return await svc.invite(session, ctx, request, body, settings)
    except svc.MemberError as exc:
        raise _http(exc) from None


@router.patch("/{member_id}")
async def update_member(
    member_id: uuid.UUID, body: MemberPatch, ctx: AdminCtx, request: Request, session: SessionDep
) -> MemberOut:
    try:
        return await svc.update(session, ctx, request, member_id, body)
    except svc.MemberError as exc:
        raise _http(exc) from None


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: uuid.UUID, ctx: AdminCtx, request: Request, session: SessionDep
) -> None:
    try:
        await svc.remove(session, ctx, request, member_id)
    except svc.MemberError as exc:
        raise _http(exc) from None
