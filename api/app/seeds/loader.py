"""Load demo institutions into the DB (step 1.5). Idempotent: institution/users/memberships are
upserted; the demo tenant data (contacts, leads, slots, bookings, conversations, followups) is
replaced on every run. `reset=True` deletes the institution first (cascade) for a clean slate.

Runs in an admin-scoped transaction (platform job, explicit RLS bypass).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversations import Booking, Contact, Conversation, Followup, Lead, Slot
from app.models.core import Institution
from app.seeds.documents import ensure_documents
from app.seeds.schema import SeedFile, SlotRule
from app.services import provisioning

SUPERADMIN_EMAIL = "super@raabta.pk"
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class SeedResult:
    slug: str
    users: int
    contacts: int
    leads: int
    slots: int
    documents: list[Path]


def slot_windows(rule: SlotRule, tz: str, today: date) -> list[tuple[datetime, datetime]]:
    """Slots for `rule.weeks` weeks starting next Monday, local times converted to aware UTC."""
    zone = ZoneInfo(tz)
    start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    out = []
    for offset in range(rule.weeks * 7):
        day = start + timedelta(days=offset)
        if _WEEKDAYS[day.weekday()] not in rule.weekdays:
            continue
        for hhmm in rule.times:
            h, m = (int(x) for x in hhmm.split(":"))
            begin = datetime.combine(day, time(h, m), tzinfo=zone)
            out.append((begin, begin + timedelta(minutes=rule.duration_minutes)))
    return out


async def _clear_tenant_demo_data(session: AsyncSession, institution_id: object) -> None:
    for model in (Followup, Booking, Conversation, Lead, Contact, Slot):
        await session.execute(delete(model).where(model.institution_id == institution_id))


async def seed_institution(
    session: AsyncSession,
    seed: SeedFile,
    directory: Path,
    *,
    password: str,
    reset: bool = False,
    today: date | None = None,
) -> SeedResult:
    inst_seed = seed.institution
    if reset:
        await session.execute(delete(Institution).where(Institution.slug == inst_seed.slug))
    inst = await provisioning.upsert_institution(
        session,
        slug=inst_seed.slug,
        name=inst_seed.name,
        type=inst_seed.type,
        city=inst_seed.city,
        timezone=inst_seed.timezone,
        languages=list(inst_seed.languages),
        quiet_hours=dict(inst_seed.quiet_hours),
        settings=dict(inst_seed.settings),
        status="active",
    )
    for u in seed.users:
        user = await provisioning.upsert_user(
            session, email=u.email, name=u.name, password=password
        )
        await provisioning.upsert_membership(
            session, institution_id=inst.id, user_id=user.id, role=u.role
        )

    await _clear_tenant_demo_data(session, inst.id)
    for c in seed.contacts:
        contact = Contact(
            institution_id=inst.id,
            wa_id=c.wa_id,
            name=c.name,
            phone=f"+{c.wa_id}",
            preferred_language=c.lang,
        )
        session.add(contact)
        await session.flush()
        session.add(
            Lead(
                institution_id=inst.id,
                contact_id=contact.id,
                guardian_name=c.name if c.lead.student_name != c.name else None,
                student_name=c.lead.student_name,
                phone=f"+{c.wa_id}",
                interest=c.lead.interest,
                status=c.lead.status,
                source=c.lead.source,
            )
        )
    windows = slot_windows(seed.slots, inst_seed.timezone, today or date.today())
    for begin, end in windows:
        session.add(
            Slot(
                institution_id=inst.id,
                kind=seed.slots.kind,
                starts_at=begin,
                ends_at=end,
                capacity=seed.slots.capacity,
                location=seed.slots.location,
            )
        )
    await session.flush()
    return SeedResult(
        slug=inst.slug,
        users=len(seed.users),
        contacts=len(seed.contacts),
        leads=len(seed.contacts),
        slots=len(windows),
        documents=ensure_documents(seed, directory),
    )


async def seed_superadmin(session: AsyncSession, password: str) -> None:
    await provisioning.upsert_user(
        session,
        email=SUPERADMIN_EMAIL,
        name="RaabtaAI Super Admin",
        password=password,
        is_superadmin=True,
    )
