"""`AGENT_LLM=demo` — a deterministic, zero-spend stand-in for Claude so the widget/chat API can be
run and clicked through locally (step 4.1) without an API key. Never allowed in prod.

Keyword routing only: visit/slot words → `get_visit_slots`, fee words → `get_fee_table`, else
`search_knowledge`; the reply quotes the tool output so the numeric grounding guard passes."""

import json
import re
from typing import Any

from app.agent.schemas import CheckResult, GuardVerdict, RouteDecision, Summary
from app.kb.text import detect_lang
from app.llm.fake import FakeLLM, text_reply, tool_call

NEW_MESSAGE = re.compile(r"<new_message>\n(.*?)\n</new_message>", re.S)
VISIT_WORDS = re.compile(r"\b(visit|book|slot|tour|appointment|counsell?ing)\b|وزٹ", re.I)
FEE_WORDS = re.compile(r"\b(fee|fees|tuition|charges|kitni)\b|فیس", re.I)


def _text(messages: list[dict[str, Any]]) -> str:
    content = messages[0]["content"] if messages else ""
    blob = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    if not isinstance(content, str):
        blob = "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    m = NEW_MESSAGE.search(blob)
    return (m.group(1) if m else blob).strip()


def _guard(req: dict[str, Any]) -> GuardVerdict:
    lang = detect_lang(_text(req["messages"]))
    return GuardVerdict(
        language=lang if lang in ("en", "ur", "roman_ur") else "en",
        injection=False,
        abuse=False,
        pii_request=False,
        off_topic=False,
        reason="demo",
    )


def _route(req: dict[str, Any]) -> RouteDecision:
    text = _text(req["messages"])
    intent = (
        "visit"
        if VISIT_WORDS.search(text)
        else "fee_structure"
        if FEE_WORDS.search(text)
        else "enquiry"
    )
    return RouteDecision(
        module="admissions",
        intents=[intent],
        complexity="simple",
        needs_identity=False,
        skills=[],
        search_queries=[text[:120]],
        confidence=0.9,
    )


def _agent(req: dict[str, Any]) -> Any:
    msgs = req["messages"]
    results = [
        b
        for m in msgs
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    text = _text(msgs)
    if not results:
        if VISIT_WORDS.search(text):
            return tool_call(
                "get_visit_slots", {"kind": "visit", "from_date": None, "to_date": None}
            )
        if FEE_WORDS.search(text):
            return tool_call("get_fee_table", {"program_or_class": None, "academic_year": None})
        return tool_call("search_knowledge", {"queries": [text[:120]], "top_k": 3})
    body = results[-1].get("content")
    raw = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    words = raw.split()
    excerpt = " ".join(words[:60])  # whole tokens only: a cut number would fail grounding
    return text_reply(f"(Demo mode — no AI) Here is what I found:\n\n{excerpt}")


def _summary(_req: dict[str, Any]) -> Summary:
    return Summary.model_validate(
        {
            "facts": [],
            "open_questions": [],
            "lead": {"student_name": None, "guardian_name": None, "phone": None, "interest": None},
            "profile": {
                "guardian_name": None,
                "student_name": None,
                "student_class": None,
                "preferred_language": None,
                "phone": None,
            },
            "stage": "exploring",
            "goal_status": "answered",
            "verified": False,
            "last_promise": None,
        }
    )


def demo_llm() -> FakeLLM:
    ok = CheckResult(
        claims=[], language_ok=True, identity_leak=False, ok=True, unsupported_claims=[], fixes=[]
    )
    llm = FakeLLM(
        {
            "guard_in": _guard,
            "router": _route,
            "agent_simple": _agent,
            "agent_complex": _agent,
            "answer_check": ok,
            "tone_check": ok,
            "summarizer": _summary,
        }
    )
    llm.mode = "demo"
    return llm
