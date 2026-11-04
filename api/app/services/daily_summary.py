"""Daily principal summary (step 6.7.2): counts for the institution's day + top questions,
sent at 18:00 PKT via the `daily_summary` template to `settings.daily_summary.numbers`, and served
in-app by `GET /metrics/daily-summary`. Deterministic SQL — no LLM."""

import datetime as dt
import logging
import re
from collections import Counter
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp.client import WhatsAppError
from app.channels.whatsapp.templates import meta_language, meta_name, render
from app.core.tenancy import admin_session, tenant_session
from app.models.conversations import Booking, Contact, Conversation, Lead, Message
from app.models.core import Institution
from app.models.templates import Template
from app.services.whatsapp import WhatsAppDeps

log = logging.getLogger(__name__)
SANDBOX = "sandbox-%"  # playground contacts (step 5.7.4) never count


def _bounds(day: dt.date, tz: str) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(day, dt.time(0), ZoneInfo(tz))
    return start, start + dt.timedelta(days=1)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s؀-ۿ?]", " ", text.lower())).strip()[:80]


async def build_summary(session: AsyncSession, inst: Institution, day: dt.date) -> dict[str, Any]:
    start, end = _bounds(day, inst.timezone)
    real = Contact.widget_visitor_id.is_(None) | Contact.widget_visitor_id.not_like(SANDBOX)
    conv_ids = (
        select(Conversation.id)
        .join(Contact, Contact.id == Conversation.contact_id)
        .where(real, Conversation.updated_at >= start, Conversation.updated_at < end)
    )
    conversations = await session.scalar(select(func.count()).select_from(conv_ids.subquery()))
    first_texts = (
        await session.execute(
            select(Message.conversation_id, Message.text)
            .where(
                Message.conversation_id.in_(conv_ids),
                Message.direction == "in",
                Message.text.is_not(None),
                Message.created_at >= start,
                Message.created_at < end,
            )
            .order_by(Message.conversation_id, Message.seq)
        )
    ).all()
    seen: set[Any] = set()
    questions: Counter[str] = Counter()
    for cid, text in first_texts:
        if cid not in seen and text:
            seen.add(cid)
            questions[_norm(text)] += 1
    leads = await session.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.created_at >= start, Lead.created_at < end)
    )
    bookings = await session.scalar(
        select(func.count())
        .select_from(Booking)
        .where(Booking.created_at >= start, Booking.created_at < end)
    )
    flagged = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.status != "closed",
            (Conversation.flagged.is_(True)) | (Conversation.mode == "human"),
        )
    )
    return {
        "date": day.isoformat(),
        "day": day.strftime("%a %d %b"),
        "institution": inst.name,
        "conversations": int(conversations or 0),
        "leads": int(leads or 0),
        "bookings": int(bookings or 0),
        "flagged": int(flagged or 0),
        "top_questions": [q for q, _ in questions.most_common(3) if q],
    }


async def send_daily_summaries(deps: WhatsAppDeps, now: dt.datetime | None = None) -> int:
    """Send today's summary to each institution's configured numbers. Template only (principals
    are not contacts, so there is no 24h window); skipped until the template is approved."""
    now = now or dt.datetime.now(dt.UTC)
    if deps.client is None:
        return 0
    async with admin_session(deps.sessionmaker) as session:
        ids = (
            await session.scalars(
                select(Institution.id).where(
                    Institution.status != "suspended", Institution.wa_phone_number_id.is_not(None)
                )
            )
        ).all()
    sent = 0
    for inst_id in ids:
        async with tenant_session(deps.sessionmaker, inst_id) as session:
            inst = await session.get(Institution, inst_id)
            if inst is None:
                continue
            cfg = (inst.settings or {}).get("daily_summary") or {}
            numbers = [re.sub(r"\D", "", str(n)) for n in cfg.get("numbers") or []]
            numbers = [n for n in numbers if 10 <= len(n) <= 15]
            if not cfg.get("enabled", True) or not numbers or not inst.wa_phone_number_id:
                continue
            lang = cfg.get("language") or "roman_ur"
            tpls = {
                t.language: t
                for t in (
                    await session.scalars(
                        select(Template).where(
                            Template.name == "daily_summary", Template.status == "approved"
                        )
                    )
                ).all()
            }
            tpl = tpls.get(lang) or tpls.get("roman_ur") or tpls.get("en")
            if tpl is None:
                log.info("daily summary skipped for %s: template not approved", inst_id)
                continue
            summary = await build_summary(
                session, inst, now.astimezone(ZoneInfo(inst.timezone)).date()
            )
            _, params = render(tpl, {k: str(v) for k, v in summary.items()})
            for number in numbers:
                try:
                    await deps.client.send_template(
                        inst.wa_phone_number_id,
                        number,
                        meta_name(tpl),
                        meta_language(tpl.language),
                        params,
                    )
                    sent += 1
                except WhatsAppError as exc:
                    log.warning("daily summary send failed for %s: %s", inst_id, exc)
    return sent
