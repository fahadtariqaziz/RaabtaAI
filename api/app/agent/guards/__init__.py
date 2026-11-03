"""Deterministic guards (PLAN §10): opt-out keywords (G7), injection pre-filter (G1), language /
script detection (G14), loop & cost caps (G13), per-contact rate limit (G8). LLM guards live in
the graph nodes (guard_in, answer_check)."""

import datetime as dt
import re
import uuid
from typing import Any

from app.kb.text import detect_lang, looks_like_injection

MAX_TOOL_ITERATIONS = 6
DAILY_AI_TURNS = 40  # per conversation per day
CONTACT_RATE = (20, 600)  # 20 messages per 10 minutes
ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
LATIN = re.compile(r"[A-Za-z]")

OPT_OUT = (
    "stop",
    "unsubscribe",
    "band karo",
    "band karein",
    "band kar do",
    "msg na karen",
    "msg na karein",
    "message na karen",
    "message na karein",
    "messages band",
    "mat bhejo",
    "mat bhejein",
    "روکیں",
    "روک دیں",
    "بند کریں",
    "پیغام نہ بھیجیں",
)
OPT_IN = ("start", "unstop", "شروع")


def _clean(text: str) -> str:
    return re.sub(r"[^\w\s؀-ۿ]", " ", text.lower()).strip()


def is_opt_out(text: str) -> bool:
    """Whole short message is an opt-out phrase (so "bus stop kahan hai?" is not)."""
    clean = " ".join(_clean(text).split())
    if not clean or len(clean.split()) > 5:
        return False
    return any(clean == k or clean.startswith(k + " ") or clean.endswith(" " + k) for k in OPT_OUT)


def is_opt_in(text: str) -> bool:
    return " ".join(_clean(text).split()) in OPT_IN


def injection_prefilter(text: str) -> bool:
    return looks_like_injection(text)


def detect_language(text: str) -> str:
    return detect_lang(text)


def script_ok(expected: str, reply: str) -> bool:
    """G14 (deterministic part): Urdu-script contact → reply has Urdu script; Roman-Urdu or
    English contact → reply mostly Latin. `mixed` accepts either."""
    arabic, latin = len(ARABIC.findall(reply)), len(LATIN.findall(reply))
    if expected == "ur":
        return arabic > 0 and arabic >= latin * 0.5
    if expected in ("en", "roman_ur"):
        return arabic <= max(3, latin * 0.1)
    return True


async def allow_contact_message(
    redis: Any, institution_id: uuid.UUID, contact_id: uuid.UUID, now: dt.datetime
) -> bool:
    """Fixed-window per-contact limit (G8). No Redis → allow (tests/CLI)."""
    if redis is None:
        return True
    limit, window = CONTACT_RATE
    bucket = int(now.timestamp()) // window
    key = f"rl:contact:{institution_id}:{contact_id}:{bucket}"
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, window)
    return count <= limit


async def take_daily_turn(
    redis: Any, conversation_id: uuid.UUID, today: dt.date, cap: int = DAILY_AI_TURNS
) -> bool:
    """G13 per-conversation daily cap on AI turns. No Redis → allow."""
    if redis is None:
        return True
    key = f"cap:conv:{conversation_id}:{today.isoformat()}"
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, 2 * 86400)
    return count <= cap


async def first_delivery(redis: Any, institution_id: uuid.UUID, message_key: str | None) -> bool:
    """Inbound dedupe (wa_message_id / client_msg_id): True the first time only."""
    if redis is None or not message_key:
        return True
    return bool(await redis.set(f"inbound:{institution_id}:{message_key}", 1, nx=True, ex=86400))
