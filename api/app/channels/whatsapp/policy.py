"""Outbound policy gate (step 6.8, PLAN §6.2 policy_gate, G6/G7/G8). Deterministic, per item,
applied to every proactive send (follow-ups, reminders, sequences) — never to replies to an
inbound message.

Order: opted out → cancel · conversation with staff → cancel · plan limit → hold · quiet hours /
Jumma → reschedule to the window end · weekly per-contact cap → reschedule +1 day."""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal
from zoneinfo import ZoneInfo

DEFAULT_QUIET = {"start": "20:00", "end": "09:00"}
DEFAULT_JUMMA = {"start": "12:30", "end": "14:30"}  # Friday prayers
WEEKLY_CAP = 3

Action = Literal["send", "cancel", "reschedule", "hold"]


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str = ""
    when: dt.datetime | None = None  # reschedule target (UTC)


def _hm(value: Any, default: str) -> dt.time:
    try:
        h, m = str(value or default).split(":")
        return dt.time(int(h), int(m))
    except ValueError:
        h, m = default.split(":")
        return dt.time(int(h), int(m))


def _in(t: dt.time, start: dt.time, end: dt.time) -> bool:
    return (start <= t < end) if start <= end else (t >= start or t < end)


def quiet_until(now: dt.datetime, tz_name: str, quiet: dict[str, Any] | None) -> dt.datetime | None:
    """If `now` falls in the institution's quiet hours or the Friday Jumma window, return when
    sending may resume (UTC); else None. `quiet` = institutions.quiet_hours
    ({"start","end", optional "jumma": {"start","end"} | false})."""
    tz = ZoneInfo(tz_name)
    q = quiet or {}
    start, end = (
        _hm(q.get("start"), DEFAULT_QUIET["start"]),
        _hm(q.get("end"), DEFAULT_QUIET["end"]),
    )
    jumma_cfg = q.get("jumma", DEFAULT_JUMMA)
    local = now.astimezone(tz)
    resume: dt.datetime | None = None
    if start != end and _in(local.time(), start, end):
        day = local.date() if local.time() < end else local.date() + dt.timedelta(days=1)
        resume = dt.datetime.combine(day, end, tz)
    elif jumma_cfg and local.weekday() == 4:
        js = _hm(jumma_cfg.get("start"), DEFAULT_JUMMA["start"])
        je = _hm(jumma_cfg.get("end"), DEFAULT_JUMMA["end"])
        if _in(local.time(), js, je):
            resume = dt.datetime.combine(local.date(), je, tz)
    return resume.astimezone(dt.UTC) if resume else None


def gate(
    now: dt.datetime,
    *,
    tz_name: str,
    quiet: dict[str, Any] | None,
    opted_out: bool,
    human_mode: bool,
    sent_last_7d: int,
    over_plan: bool,
    weekly_cap: int = WEEKLY_CAP,
) -> Decision:
    if opted_out:
        return Decision("cancel", "contact opted out")
    if human_mode:
        return Decision("cancel", "conversation is with staff")
    if over_plan:
        return Decision("hold", "monthly template limit reached")
    resume = quiet_until(now, tz_name, quiet)
    if resume is not None:
        return Decision("reschedule", "quiet hours", resume)
    if sent_last_7d >= weekly_cap:
        return Decision("reschedule", "weekly cap", now + dt.timedelta(days=1))
    return Decision("send")
