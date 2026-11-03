"""Context assembly (step 3.6): cache order, determinism, budgets, no timestamps in cached blocks,
append-only prefix across loop iterations, compaction across turns."""

import datetime as dt
import json
import re
from typing import Any

from app.agent import context as c
from app.agent.skills_loader import TurnFacts, select
from app.agent.tools import build_registry
from app.kb.text import estimate_tokens
from app.llm.claude import TurnPrefixGuard
from app.prompts import render_tenant_block

NOW = dt.datetime(2026, 11, 3, 5, 0, tzinfo=dt.UTC)
TENANT = render_tenant_block(
    {
        "name": "ABC Grammar School",
        "type": "school",
        "city": "Lahore",
        "languages": ["en", "ur", "roman_ur"],
        "academic_year": "2026-27",
        "cta": "invite the parent for a campus visit",
        "details": {"phone": "+92 42 3575 1100"},
        "facts_version": 3,
    }
)
# What the volatile turn block injects (ISO dates, full month/weekday names). Static examples
# like "10:00 AM" or the academic-year label never change between requests, so they may stay.
DATEISH = re.compile(r"\b20\d\d-\d\d-\d\d\b|November|Tuesday")


def request(**over: Any) -> c.AgentRequest:
    args: dict[str, Any] = {
        "module": "admissions",
        "tenant_block": TENANT,
        "skills": select(
            TurnFacts("school", "admissions", ("fee_structure",), language="roman_ur")
        ),
        "tools": build_registry().definitions("admissions"),
        "turn": c.turn_context(
            now=NOW,
            timezone="Asia/Karachi",
            academic_year="2026-27",
            channel="widget",
            language="roman_ur",
            verified=False,
            contact={"name": "Ayesha", "student_class": "Class 3", "student_name": None},
        ),
        "summary": {"facts": ["Asked fee"], "stage": "exploring", "lead": {"phone": None}},
        "history": [{"role": "user", "text": "Salam"}, {"role": "assistant", "text": "Walaikum"}],
        "message": "Class 3 ki fee?",
    }
    args.update(over)
    return c.build_agent_request(**args)


def test_cache_order_and_breakpoints() -> None:
    req = request()
    assert [b["cache_control"] for b in req.system] == [c.CACHE] * 3
    assert req.system[0]["text"].startswith("You are RaabtaAI")
    assert "# Role: admissions assistant" in req.system[0]["text"]
    assert req.system[1]["text"] == TENANT
    assert req.system[2]["text"].startswith("# Skill: admissions-school")
    assert [t["name"] for t in req.tools] == sorted(t["name"] for t in req.tools)
    fees = request(module="fees", skills=[])
    assert len(fees.system) == 2 and "# Role: fee desk assistant" in fees.system[0]["text"]
    assert fees.prompt_hash != req.prompt_hash and len(req.prompt_hash) == 16


def test_deterministic_bytes_and_no_timestamps_in_cached_blocks() -> None:
    a, b = request(), request()
    assert json.dumps(a.__dict__, sort_keys=True) == json.dumps(b.__dict__, sort_keys=True)
    for block in a.system:
        assert not DATEISH.search(block["text"]), block["text"][:80]
    first = a.messages[0]["content"][0]["text"]
    assert "Today: Tuesday 03 November 2026, 10:00 (Asia/Karachi)" in first
    assert "Verified parent: no" in first and "Reply language: roman_ur" in first
    # a different contact/time changes only the volatile user block
    later = request(
        turn=c.turn_context(
            now=NOW + dt.timedelta(days=1),
            timezone="Asia/Karachi",
            academic_year="2026-27",
            channel="whatsapp",
            language="en",
            verified=True,
            contact={},
        ),
        summary=None,
        history=[],
        message="hi",
    )
    assert later.system == a.system and later.tools == a.tools
    assert later.messages != a.messages
    assert [b["text"].split("\n")[0] for b in later.messages[0]["content"]] == [
        "<turn_context>",
        "<new_message>",
    ]


def test_prefix_is_append_only_across_tool_loop() -> None:
    req = request()
    guard = TurnPrefixGuard()
    msgs = list(req.messages)
    guard.check(req.tools, req.system, msgs)
    msgs.append({"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "x"}]})
    msgs.append(
        c.tool_results_message([{"type": "tool_result", "tool_use_id": "t", "content": "{}"}])
    )
    guard.check(req.tools, req.system, msgs)
    msgs = c.append_operator_note(msgs, "Review note")  # after tool results → system message
    guard.check(req.tools, req.system, msgs)
    assert msgs[-1] == {"role": "system", "content": "Review note"}
    msgs.append({"role": "assistant", "content": [{"type": "text", "text": "draft"}]})
    msgs = c.append_operator_note(msgs, "Fix the total")  # after final text → marked user turn
    guard.check(req.tools, req.system, msgs)
    assert msgs[-1]["role"] == "user"
    assert "not_from_contact" in msgs[-1]["content"][0]["text"]


def test_budgets_with_priority() -> None:
    long_history = [
        {"role": "user" if i % 2 == 0 else "assistant", "text": f"message number {i} " + "x" * 400}
        for i in range(30)
    ]
    text = c.history_text(long_history)
    assert estimate_tokens(text) <= c.BUDGET["history"]
    assert "message number 29" in text and "message number 0 " not in text  # newest kept
    big_summary = {"facts": ["fact " * 50 for _ in range(20)], "stage": "exploring"}
    assert estimate_tokens(c.summary_text(big_summary)) <= c.BUDGET["summary"] + 2
    huge = request(message="fee " * 5000)
    new_msg = huge.messages[0]["content"][-1]["text"]
    assert estimate_tokens(new_msg) <= c.BUDGET["message"] + 10
    assert c.summary_text(None) == "" and c.summary_text({"lead": {"phone": None}}) == "{}"


def test_history_collapses_tool_calls_and_resets_when_idle() -> None:
    line = c.collapse_tools(
        [
            {"name": "get_fee_table", "input": {"program_or_class": "Class 3"}},
            {"name": "get_fee_table", "input": {"program_or_class": "Class 3"}},
            {"name": "get_transport_routes", "input": {"area": None}, "is_error": True},
        ]
    )
    assert line == "[looked up: fee table (Class 3), transport routes — failed]"
    history = [
        {"role": "user", "text": "fee?"},
        {"role": "assistant", "text": "PKR 12,500", "tools": line},
        {"role": "staff", "text": "Principal will call"},
    ]
    assert c.history_text(history).splitlines() == [
        "User: fee?",
        line,
        "Assistant: PKR 12,500",
        "Staff: Principal will call",
    ]
    recent = (NOW - dt.timedelta(days=2)).isoformat()
    stale = (NOW - dt.timedelta(days=8)).isoformat()
    assert c.reset_history_if_idle(history, recent, NOW) == history
    assert c.reset_history_if_idle(history, stale, NOW) == []
    assert c.reset_history_if_idle(history, None, NOW) == history
