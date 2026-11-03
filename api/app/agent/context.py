"""Deterministic context assembly (PLAN §7, step 3.6).

Cache order of every agent request: tools (name-sorted module subset) → system[0] global rules +
persona (cached) → system[1] tenant block (cached; carries `facts_version`, no timestamps) →
system[2] skills (cached) → messages. Everything volatile — date/time, contact profile, verified
flag, summary, recent history, the new message — goes in the FIRST user message of the turn.
Within a turn the message list is append-only (operator notes = appended `role: system`
messages); across turns the context is rebuilt from summary + last 6 turns as text (no thinking
replay). Budgets are enforced here with priority: new message > tool results > summary >
history > skills."""

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from app.agent.skills_loader import SKILLS_BUDGET, Skill, render
from app.kb.text import estimate_tokens
from app.prompts import load_prompt, tenant_block_version

CACHE = {"type": "ephemeral"}
HISTORY_TURNS = 6
BUDGET = {"message": 2000, "summary": 400, "history": 1200, "turn": 200, "skills": SKILLS_BUDGET}
IDLE_RESET = dt.timedelta(days=7)
ROLE_LABELS = {"user": "User", "assistant": "Assistant", "staff": "Staff"}
TOOL_LABELS = {
    "search_knowledge": "documents",
    "get_fee_table": "fee table",
    "get_programs": "programs",
    "get_key_dates": "key dates",
    "get_scholarships": "scholarships",
    "get_transport_routes": "transport routes",
    "get_visit_slots": "visit slots",
    "book_visit": "booked a slot",
    "save_lead": "saved lead",
    "schedule_followup": "scheduled follow-up",
    "handoff_to_human": "handed off to staff",
    "set_contact_language": "set language",
}


def truncate_tokens(text: str, budget: int, *, keep: str = "head") -> str:
    """Trim to ~`budget` tokens (same estimator as the KB). `keep="tail"` keeps the end."""
    if estimate_tokens(text) <= budget:
        return text
    chars = int(len(text) * budget / max(estimate_tokens(text), 1))
    return "…" + text[-chars:] if keep == "tail" else text[:chars] + "…"


def persona_name(module: str) -> str:
    return "agent_fees" if module == "fees" else "agent_admissions"


def system_blocks(module: str, tenant_block: str, skills: list[Skill]) -> list[dict[str, Any]]:
    """Cached system blocks. Identical inputs → identical bytes (cache hits across contacts)."""
    rules = f"{load_prompt('system_global').text}\n\n{load_prompt(persona_name(module)).text}"
    blocks = [
        {"type": "text", "text": rules, "cache_control": CACHE},
        {"type": "text", "text": tenant_block, "cache_control": CACHE},
    ]
    skills_text = render(skills)
    if skills_text:
        blocks.append(
            {
                "type": "text",
                "text": truncate_tokens(skills_text, BUDGET["skills"]),
                "cache_control": CACHE,
            }
        )
    return blocks


def prompt_fingerprint(module: str) -> str:
    """Logged as `llm_runs.prompt_hash` for agent calls: global + persona + tenant template."""
    parts = [load_prompt("system_global"), load_prompt(persona_name(module))]
    raw = "|".join(f"{p.tag}:{p.hash}" for p in parts) + f"|tenant_block@{tenant_block_version()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def collapse_tools(tool_calls: list[dict[str, Any]]) -> str:
    """`[looked up: fee table (Class 3), key dates]` — history keeps actions, not payloads."""
    if not tool_calls:
        return ""
    parts: list[str] = []
    for call in tool_calls:
        label = TOOL_LABELS.get(call["name"], call["name"])
        hint = next(
            (
                str(v)
                for k, v in (call.get("input") or {}).items()
                if k in ("program_or_class", "kind", "area", "level") and v
            ),
            "",
        )
        item = f"{label} ({hint})" if hint else label
        if call.get("is_error"):
            item += " — failed"
        if item not in parts:
            parts.append(item)
    return f"[looked up: {', '.join(parts)}]"


def history_text(history: list[dict[str, Any]], budget: int = BUDGET["history"]) -> str:
    """Last 6 turns as `User:`/`Assistant:` lines; oldest lines dropped first to fit."""
    lines: list[str] = []
    for item in history[-2 * HISTORY_TURNS :]:
        role = {"user": "User", "assistant": "Assistant", "staff": "Staff"}.get(
            item["role"], "Note"
        )
        if item.get("tools"):
            lines.append(item["tools"])
        lines.append(f"{role}: {item['text']}")
    while lines and estimate_tokens("\n".join(lines)) > budget:
        lines.pop(0)
    return "\n".join(lines)


def summary_text(summary: dict[str, Any] | None, budget: int = BUDGET["summary"]) -> str:
    if not summary:
        return ""
    keep = {
        k: v
        for k, v in summary.items()
        if v not in (None, [], {}, "")
        and k
        in ("facts", "open_questions", "lead", "profile", "stage", "goal_status", "last_promise")
    }
    for key in ("lead", "profile"):
        if isinstance(keep.get(key), dict):
            keep[key] = {k: v for k, v in keep[key].items() if v}
            if not keep[key]:
                keep.pop(key)
    return truncate_tokens(json.dumps(keep, ensure_ascii=False, sort_keys=True), budget)


def turn_context(
    *,
    now: dt.datetime,
    timezone: str,
    academic_year: str | None,
    channel: str,
    language: str,
    verified: bool,
    contact: dict[str, Any],
) -> str:
    local = now.astimezone(ZoneInfo(timezone))
    profile = {k: v for k, v in sorted(contact.items()) if v}
    lines = [
        f"Today: {local.strftime('%A %d %B %Y, %H:%M')} ({timezone})",
        f"Academic year: {academic_year or 'not stated'}",
        f"Channel: {channel}",
        f"Contact: {json.dumps(profile, ensure_ascii=False) if profile else 'unknown'}",
        f"Verified parent: {'yes' if verified else 'no'}",
        f"Reply language: {language}",
    ]
    return truncate_tokens("\n".join(lines), BUDGET["turn"])


def first_user_message(
    *,
    turn: str,
    summary: dict[str, Any] | None,
    history: list[dict[str, Any]],
    message: str,
) -> dict[str, Any]:
    blocks = [{"type": "text", "text": f"<turn_context>\n{turn}\n</turn_context>"}]
    s = summary_text(summary)
    if s:
        blocks.append(
            {"type": "text", "text": f"<conversation_summary>\n{s}\n</conversation_summary>"}
        )
    h = history_text(history)
    if h:
        blocks.append({"type": "text", "text": f"<recent_history>\n{h}\n</recent_history>"})
    msg = truncate_tokens(message.strip(), BUDGET["message"])
    blocks.append({"type": "text", "text": f"<new_message>\n{msg}\n</new_message>"})
    return {"role": "user", "content": blocks}


def operator_note(text: str) -> dict[str, Any]:
    """Mid-turn instruction (repair feedback, staff note): appended, never an edit."""
    return {"role": "system", "content": text}


def append_operator_note(messages: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Append (never edit) an operator note. The API accepts `role: system` only right after a
    user message (incl. tool results); after the assistant's final text the note goes in as a
    user turn, clearly marked as coming from the system, not the contact (I-15)."""
    if messages and messages[-1].get("role") == "user":
        return [*messages, operator_note(text)]
    wrapped = f'<operator_note from="system" not_from_contact="true">\n{text}\n</operator_note>'
    return [*messages, {"role": "user", "content": [{"type": "text", "text": wrapped}]}]


def tool_results_message(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """All tool_results of one assistant step go back in ONE user message."""
    return {"role": "user", "content": blocks}


def reset_history_if_idle(
    history: list[dict[str, Any]], last_turn_at: str | None, now: dt.datetime
) -> list[dict[str, Any]]:
    """Idle > 7 days: keep the summary, drop history text (PLAN §7)."""
    if last_turn_at and now - dt.datetime.fromisoformat(last_turn_at) > IDLE_RESET:
        return []
    return history


@dataclass(frozen=True)
class AgentRequest:
    system: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    prompt_hash: str
    skills: list[str]


def build_agent_request(
    *,
    module: str,
    tenant_block: str,
    skills: list[Skill],
    tools: list[dict[str, Any]],
    turn: str,
    summary: dict[str, Any] | None,
    history: list[dict[str, Any]],
    message: str,
) -> AgentRequest:
    return AgentRequest(
        system=system_blocks(module, tenant_block, skills),
        tools=tools,
        messages=[first_user_message(turn=turn, summary=summary, history=history, message=message)],
        prompt_hash=prompt_fingerprint(module),
        skills=[s.tag for s in skills],
    )
