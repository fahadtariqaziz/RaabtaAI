"""Create/update institutions, users and memberships idempotently (seeds, tests, superadmin).

Callers pass an admin-scoped session (`admin_session` / `scope_to_admin`) — these writes cross
tenants by design.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.core import Institution, Membership, User


async def upsert_institution(
    session: AsyncSession, *, slug: str, name: str, type: str, city: str, **fields: Any
) -> Institution:
    inst = await session.scalar(select(Institution).where(Institution.slug == slug))
    if inst is None:
        inst = Institution(slug=slug, name=name, type=type, city=city, **fields)
        session.add(inst)
    else:
        inst.name, inst.type, inst.city = name, type, city
        for key, value in fields.items():
            setattr(inst, key, value)
    await session.flush()
    return inst


async def upsert_user(
    session: AsyncSession,
    *,
    email: str,
    name: str,
    password: str | None = None,
    is_superadmin: bool = False,
) -> User:
    email = email.strip().lower()
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name, is_superadmin=is_superadmin)
        session.add(user)
    else:
        user.name, user.is_superadmin = name, is_superadmin
    if password is not None:
        user.password_hash = hash_password(password)
    await session.flush()
    return user


async def upsert_membership(
    session: AsyncSession,
    *,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    status: str = "active",
) -> Membership:
    m = await session.scalar(
        select(Membership).where(
            Membership.institution_id == institution_id, Membership.user_id == user_id
        )
    )
    if m is None:
        m = Membership(institution_id=institution_id, user_id=user_id, role=role, status=status)
        session.add(m)
    else:
        m.role, m.status = role, status
    await session.flush()
    return m
