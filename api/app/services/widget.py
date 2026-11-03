"""Public web widget (PLAN §15.1, step 4.1): per-institution widget config, visitor session
tokens, origin allowlist, rate limits / abuse lockout, and mapping a `TurnResult` to SSE events.

Institution settings key `widget` (a dict, so it never enters the cached tenant prompt block):
  {allowed_origins: [...], primary_color, position, whatsapp_number, suggested_questions:
   {en: [...], ur: [...], roman_ur: [...]}, welcome: {en, ur, roman_ur}}"""

import datetime as dt
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import jwt

from app.agent.inbound import TurnResult
from app.core.config import Settings
from app.core.security import JWT_ALGORITHM
from app.models.core import Institution

VISITOR_RE = re.compile(r"^v_[A-Za-z0-9_-]{8,48}$")
MAX_MESSAGE_CHARS = 1000
SESSION_RATE_PER_IP = (30, 3600)  # new sessions per IP per hour
MSG_RATE_PER_IP = (60, 600)
MSG_RATE_PER_SESSION = (30, 600)
ABUSE_STRIKES = 3  # blocked turns in one session → lockout
ABUSE_LOCK_SECONDS = 3600
WA_LINK_TTL = 30 * 86400
DEV_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
BOOKING_INTENTS = {"visit", "test", "counselling", "interest"}

DEFAULT_PRIMARY = {"school": "#0f766e", "college": "#1d4ed8", "university": "#7c3aed"}
WELCOME = {
    "en": "Assalam-o-Alaikum! Ask me anything about admissions, fees or visits at {name}.",
    "roman_ur": "Assalam-o-Alaikum! {name} mein admission, fees ya visit ke baare mein poochein.",
    "ur": "السلام علیکم! {name} میں داخلے، فیس یا وزٹ کے بارے میں پوچھیں۔",
}
SUGGESTED = {
    "school": {
        "en": ["What is the fee for Class 3?", "When do admissions open?", "Book a campus visit"],
        "roman_ur": [
            "Class 3 ki fee kitni hai?",
            "Admission kab open hain?",
            "Visit book karni hai",
        ],
        "ur": ["کلاس 3 کی فیس کتنی ہے؟", "داخلے کب شروع ہیں؟", "کیمپس وزٹ بک کرنی ہے"],
    },
    "college": {
        "en": ["Which programs do you offer?", "What is the FSc fee?", "Is there a scholarship?"],
        "roman_ur": ["Kaun se programs hain?", "FSc ki fee kitni hai?", "Scholarship milti hai?"],
        "ur": ["کون سے پروگرام ہیں؟", "ایف ایس سی کی فیس کتنی ہے؟", "کیا اسکالرشپ ملتی ہے؟"],
    },
    "university": {
        "en": ["What is the BSCS fee?", "What is the last date to apply?", "Eligibility for BBA?"],
        "roman_ur": [
            "BSCS ki fee kitni hai?",
            "Apply ki last date kya hai?",
            "BBA ki eligibility?",
        ],
        "ur": ["بی ایس سی ایس کی فیس کتنی ہے؟", "اپلائی کی آخری تاریخ؟", "بی بی اے کی اہلیت؟"],
    },
}
STATUS = {  # tool → status line while it runs (UI language)
    "search_knowledge": {
        "en": "Searching the prospectus…",
        "roman_ur": "Prospectus dekh raha hoon…",
        "ur": "پراسپیکٹس دیکھ رہا ہوں…",
    },
    "get_fee_table": {
        "en": "Checking the fee table…",
        "roman_ur": "Fee table check kar raha hoon…",
        "ur": "فیس ٹیبل دیکھ رہا ہوں…",
    },
    "get_visit_slots": {
        "en": "Looking for open slots…",
        "roman_ur": "Khaali slots dekh raha hoon…",
        "ur": "دستیاب اوقات دیکھ رہا ہوں…",
    },
    "book_visit": {
        "en": "Booking your slot…",
        "roman_ur": "Aap ka slot book kar raha hoon…",
        "ur": "آپ کا وقت بک کر رہا ہوں…",
    },
    "_default": {
        "en": "Checking our records…",
        "roman_ur": "Record check kar raha hoon…",
        "ur": "ریکارڈ دیکھ رہا ہوں…",
    },
    "_thinking": {"en": "Thinking…", "roman_ur": "Soch raha hoon…", "ur": "سوچ رہا ہوں…"},
    "_human": {
        "en": "Our team will reply here shortly.",
        "roman_ur": "Hamari team jald yahan jawab degi.",
        "ur": "ہماری ٹیم جلد یہاں جواب دے گی۔",
    },
}
WA_TEXT = {
    "en": "Hi, I was chatting on your website (ref {code}).",
    "roman_ur": "Assalam-o-Alaikum, main website par baat kar raha tha (ref {code}).",
    "ur": "السلام علیکم، میں ویب سائٹ پر بات کر رہا تھا (ref {code})۔",
}


class WidgetAuthError(Exception):
    pass


def ui_lang(lang: str | None) -> str:
    return lang if lang in ("en", "ur", "roman_ur") else "en"


def status_text(tool: str, lang: str) -> str:
    return STATUS.get(tool, STATUS["_default"])[ui_lang(lang)]


def widget_settings(inst: Institution) -> dict[str, Any]:
    raw = (inst.settings or {}).get("widget")
    return dict(raw) if isinstance(raw, dict) else {}


def public_config(inst: Institution) -> dict[str, Any]:
    w = widget_settings(inst)
    langs = [lang for lang in (inst.languages or []) if lang in ("en", "ur", "roman_ur")] or ["en"]
    primary = w.get("primary_color")
    suggested = w.get("suggested_questions") or SUGGESTED.get(inst.type, SUGGESTED["school"])
    welcome = w.get("welcome") or {k: v.format(name=inst.name) for k, v in WELCOME.items()}
    return {
        "slug": inst.slug,
        "name": inst.name,
        "type": inst.type,
        "languages": langs,
        "default_language": "roman_ur" if "roman_ur" in langs else langs[0],
        "theme": {
            "primary": primary
            if isinstance(primary, str) and COLOR_RE.match(primary)
            else DEFAULT_PRIMARY.get(inst.type, "#0f766e"),
            "position": "left" if w.get("position") == "left" else "right",
        },
        "welcome": {k: welcome.get(k, "") for k in langs},
        "suggested_questions": {k: list(suggested.get(k, []))[:3] for k in langs},
        "whatsapp": bool(w.get("whatsapp_number")),
    }


def origin_allowed(origin: str | None, inst: Institution, settings: Settings) -> bool:
    """Exact scheme://host[:port] match against the allowlist; localhost always allowed in
    dev/test. No Origin header (server-side callers) is refused."""
    if not origin:
        return False
    if settings.env != "prod" and DEV_ORIGIN.match(origin):
        return True
    parts = urlsplit(origin)
    norm = f"{parts.scheme}://{parts.netloc}".lower()
    allowed = {str(o).rstrip("/").lower() for o in widget_settings(inst).get("allowed_origins", [])}
    return norm in allowed


@dataclass(frozen=True)
class WidgetSession:
    session_id: uuid.UUID
    institution_id: uuid.UUID
    contact_id: uuid.UUID
    visitor_id: str
    origin: str


def issue_session_token(
    s: WidgetSession, settings: Settings, now: dt.datetime | None = None
) -> tuple[str, dt.datetime]:
    now = now or dt.datetime.now(dt.UTC)
    exp = now + dt.timedelta(hours=settings.widget_session_ttl_hours)
    claims = {
        "typ": "widget",
        "sub": str(s.session_id),
        "inst": str(s.institution_id),
        "cid": str(s.contact_id),
        "vid": s.visitor_id,
        "org": s.origin,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), JWT_ALGORITHM), exp


def decode_session_token(token: str, session_id: uuid.UUID, settings: Settings) -> WidgetSession:
    try:
        c = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub", "typ", "inst", "cid", "vid"]},
        )
        if c["typ"] != "widget" or c["sub"] != str(session_id):
            raise WidgetAuthError("token does not match this session")
        return WidgetSession(
            session_id=uuid.UUID(c["sub"]),
            institution_id=uuid.UUID(c["inst"]),
            contact_id=uuid.UUID(c["cid"]),
            visitor_id=str(c["vid"]),
            origin=str(c.get("org", "")),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise WidgetAuthError(str(exc)) from None


def new_visitor_id() -> str:
    return "v_" + secrets.token_urlsafe(16)


async def hit(redis: Any, key: str, limit: int, window: int, now: dt.datetime) -> bool:
    """Fixed-window counter; True while within the limit."""
    bucket = int(now.timestamp()) // window
    k = f"rl:{key}:{bucket}"
    count = int(await redis.incr(k))
    if count == 1:
        await redis.expire(k, window)
    return count <= limit


async def locked_out(redis: Any, session_id: uuid.UUID) -> bool:
    return bool(await redis.exists(f"widget:lock:{session_id}"))


async def strike(redis: Any, session_id: uuid.UUID) -> None:
    """A guard-blocked turn; the 3rd in a session locks it for an hour."""
    key = f"widget:strikes:{session_id}"
    n = int(await redis.incr(key))
    await redis.expire(key, 86400)
    if n >= ABUSE_STRIKES:
        await redis.set(f"widget:lock:{session_id}", "1", ex=ABUSE_LOCK_SECONDS)


async def whatsapp_link(redis: Any, s: WidgetSession, number: str, lang: str) -> str:
    """wa.me link prefilled with a short session code; the code → (institution, contact) mapping
    lives in Redis for 30 days so the WhatsApp webhook (Phase 6) can link the two threads."""
    code = f"W{secrets.token_hex(3).upper()}"
    await redis.set(
        f"widget:wa_code:{code}",
        json.dumps({"institution_id": str(s.institution_id), "contact_id": str(s.contact_id)}),
        ex=WA_LINK_TTL,
    )
    digits = re.sub(r"\D", "", number)
    return f"https://wa.me/{digits}?text={quote(WA_TEXT[ui_lang(lang)].format(code=code))}"


def snippet(slug: str, settings: Settings) -> str:
    return f'<script src="{settings.widget_script_url}" data-institution="{slug}" async></script>'


def _slots(result: TurnResult) -> dict[str, Any] | None:
    for out in reversed(result.tool_outputs):
        if out["name"] != "get_visit_slots" or out.get("is_error"):
            continue
        try:
            data = json.loads(out["content"])
        except (TypeError, ValueError):
            return None
        slots = [
            {k: s.get(k) for k in ("slot_time", "label", "location", "seats_left")}
            for s in data.get("slots", [])
        ]
        return {"kind": data.get("kind", "visit"), "slots": slots} if slots else None
    return None


def turn_events(result: TurnResult) -> list[tuple[str, dict[str, Any]]]:
    """SSE events after the turn finished (and, for answers, after `answer_check` approved it)."""
    events: list[tuple[str, dict[str, Any]]] = []
    lang = result.language or "en"
    if result.status == "human_mode":
        return [("status", {"text": STATUS["_human"][ui_lang(lang)], "human": True})]
    if result.status == "duplicate" or not result.reply:
        return events
    events.append(
        (
            "message",
            {
                "id": result.message_id,
                "text": result.reply,
                "language": lang,
                "kind": result.reply_kind or "static",
            },
        )
    )
    if result.citations:
        events.append(
            (
                "citation",
                {
                    "citations": [
                        {
                            "title": c.get("title"),
                            "page": c.get("page"),
                            "quote": c.get("quote"),
                        }
                        for c in result.citations
                    ]
                },
            )
        )
    slots = _slots(result)
    if slots and result.reply_kind == "answer":
        events.append(("slots", slots))
    if result.quick_replies and not slots:  # the slot picker already is the CTA
        events.append(("quick_replies", {"items": result.quick_replies}))
    done = {e["type"] for e in result.events}
    lead_done = "booked" in done or any(
        e["type"] == "lead_saved" and e.get("has_phone") for e in result.events
    )
    intents = set((result.route or {}).get("intents", []))
    if result.reply_kind == "answer" and not lead_done and (slots or intents & BOOKING_INTENTS):
        events.append(("lead_form", {"fields": ["name", "phone"]}))
    return events


def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
