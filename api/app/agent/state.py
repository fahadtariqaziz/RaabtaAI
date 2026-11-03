"""Graph state (PLAN §6.1). Plain JSON-able values only (checkpointed by LangGraph).

Per-turn keys are reset by `run_inbound` on every new message (`turn_input`); persistent keys
(summary, history, goal_status, staff_notes, last_turn_at) carry over in the thread checkpoint."""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # identity + per-turn input (set by run_inbound)
    institution_id: str
    contact_id: str
    conversation_id: str
    channel: str
    now: str  # ISO, aware
    inbound: dict[str, Any]  # {text, message_id}
    tenant: dict[str, Any]  # institution profile rows (loaded under RLS)
    contact: dict[str, Any]  # {name, preferred_language, profile, verified}
    # per-turn working state
    guard: dict[str, Any] | None
    route: dict[str, Any] | None
    language: str
    context: dict[str, Any]
    turn_messages: list[dict[str, Any]]  # append-only within the turn (thinking kept)
    tool_calls: list[dict[str, Any]]
    tool_outputs: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    events: list[dict[str, Any]]
    draft: str | None
    check: dict[str, Any] | None
    repairs: int
    final: str | None
    reply_kind: str  # answer | fallback | blocked | handoff | error
    citations: list[dict[str, Any]]
    quick_replies: list[str]
    runs: list[dict[str, Any]]
    outbound_message_id: str | None
    # persistent (STM)
    summary: dict[str, Any] | None
    history: list[dict[str, Any]]
    last_turn_at: str | None
    goal_status: str
    staff_notes: list[str]


def turn_input(**identity: Any) -> AgentState:
    """Fresh per-turn state: identity fields + every working key reset."""
    state: AgentState = {
        "guard": None,
        "route": None,
        "language": "en",
        "context": {},
        "turn_messages": [],
        "tool_calls": [],
        "tool_outputs": [],
        "sources": [],
        "events": [],
        "draft": None,
        "check": None,
        "repairs": 0,
        "final": None,
        "reply_kind": "answer",
        "citations": [],
        "quick_replies": [],
        "runs": [],
        "outbound_message_id": None,
    }
    state.update(identity)  # type: ignore[typeddict-item]
    return state
