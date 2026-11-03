"""Short/long-term memory (PLAN §5 KNOW, §7 summarize; step 3.8).

STM = LangGraph checkpoint (summary, last 6 turns, goal_status). LTM = Postgres: the structured
`Summary` is written to `conversations.summary`, profile deltas to `contacts.profile` /
`preferred_language` / `name`, and a lead is upserted when the summary carries a phone the
contact typed. `goal_status` only moves up (strongest reached)."""

import json
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import Summary
from app.agent.tools.leads import normalize_pk_phone, upsert_lead
from app.models.conversations import Contact, Conversation

GOAL_RANK = {
    "open": 0,
    "answered": 1,
    "followup_scheduled": 2,
    "lead_captured": 3,
    "booked": 4,
    "handed_off": 5,
}
EVENT_GOALS = {
    "followup_scheduled": "followup_scheduled",
    "booked": "booked",
    "handoff": "handed_off",
}


def merge_goal(current: str | None, *candidates: str | None) -> str:
    best = current or "open"
    for c in candidates:
        if c and GOAL_RANK.get(c, 0) > GOAL_RANK.get(best, 0):
            best = c
    return best


def goal_from_events(events: list[dict[str, Any]], answered: bool) -> str:
    goal = "answered" if answered else "open"
    for e in events:
        if e["type"] == "lead_saved" and e.get("has_phone"):
            goal = merge_goal(goal, "lead_captured")
        goal = merge_goal(goal, EVENT_GOALS.get(e["type"]))
    return goal


def summarizer_input(
    *,
    previous: dict[str, Any] | None,
    verified: bool,
    user_text: str,
    reply: str,
    tools_line: str,
    events: list[dict[str, Any]],
    staff_notes: list[str] | None = None,
) -> str:
    """User content for the summarizer node (no tool payloads; ≤ 2.5k tokens in practice)."""
    parts = [
        f"<previous_summary>\n{json.dumps(previous or {}, ensure_ascii=False, sort_keys=True)}\n"
        "</previous_summary>",
        f"<verified>{'yes' if verified else 'no'}</verified>",
    ]
    if staff_notes:
        parts.append("<staff_notes>\n" + "\n".join(staff_notes) + "\n</staff_notes>")
    actions = [json.dumps(e, ensure_ascii=False, sort_keys=True) for e in events]
    parts.append(
        "<latest_turn>\n"
        f"Contact: {user_text}\n"
        f"{tools_line + chr(10) if tools_line else ''}"
        f"Assistant: {reply}\n"
        + (f"Actions: {'; '.join(actions)}\n" if actions else "")
        + "</latest_turn>"
    )
    return "\n".join(parts)


async def apply_summary(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    conversation_id: uuid.UUID,
    channel: str,
    summary: Summary,
    goal_status: str,
    contact_text: str = "",
) -> None:
    """Persist the summary + LTM deltas under the tenant session (RLS). A phone is only used if
    its digits occur in what the contact actually typed (`contact_text`) — never invented."""
    conv = await session.get(Conversation, conversation_id)
    contact = await session.get(Contact, contact_id)
    if conv is None or contact is None:
        return
    conv.summary = {**summary.model_dump(mode="json"), "goal_status": goal_status}
    p = summary.profile
    profile = dict(contact.profile or {})
    for key, value in (
        ("guardian_name", p.guardian_name),
        ("student_name", p.student_name or summary.lead.student_name),
        ("student_class", p.student_class or summary.lead.interest),
        ("stage", summary.stage),
    ):
        if value:
            profile[key] = value
    contact.profile = profile
    if p.preferred_language:
        contact.preferred_language = p.preferred_language
    if not contact.name and (p.guardian_name or summary.lead.guardian_name):
        contact.name = p.guardian_name or summary.lead.guardian_name
    phone = normalize_pk_phone(summary.lead.phone or p.phone)
    if phone and phone[3:] in re.sub(r"\D", "", contact_text):
        await upsert_lead(
            session,
            contact_id=contact_id,
            conversation_id=conversation_id,
            channel=channel,
            phone=phone,
            student_name=summary.lead.student_name,
            guardian_name=summary.lead.guardian_name,
            interest=summary.lead.interest,
        )
