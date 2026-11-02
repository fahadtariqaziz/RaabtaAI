"""Auth request/response schemas (PLAN §14 Auth)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["owner", "admin", "staff"]


def _lower(v: str) -> str:
    return v.strip().lower()


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)

    _norm = field_validator("email")(_lower)


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    membership_id: uuid.UUID
    institution_id: uuid.UUID
    institution_name: str
    institution_slug: str
    role: Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    name: str
    locale: str
    is_superadmin: bool


class MeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


class TokenOut(MeOut):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (OAuth token type)
    expires_in: int


class AcceptInviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    name: str | None = Field(default=None, min_length=1, max_length=120)


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    role: Role

    _norm = field_validator("email")(_lower)


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str
    role: Role
    status: Literal["invited", "active", "disabled"]
    created_at: datetime


class InviteOut(BaseModel):
    member: MemberOut
    invite_url: str
    invite_expires_at: datetime


class MemberPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None
