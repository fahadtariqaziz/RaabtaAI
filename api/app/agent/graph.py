"""LangGraph inbound graph (PLAN §6.1, step 3.5) — one graph for widget and WhatsApp.

guard_in → (blocked → safe_reply) | router → load_context → agent ⇄ tools (≤ 6 iterations)
→ handoff | answer_check → (fail, once → agent repair) | (fail again → safe_fallback)
→ compose → persist → summarize → (handoff → await_staff: interrupt()) → END

Nodes are closures over `AgentDeps` (DB sessionmaker, LLM provider, registry, embedder, Redis);
the state stays JSON-only. Opt-out, human mode, dedupe and rate limits run before the graph in
`app/agent/inbound.py`."""

import datetime as dt
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic
import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent import context as ctxb
from app.agent.guards import (
    MAX_TOOL_ITERATIONS,
    detect_language,
    injection_prefilter,
    script_ok,
)
from app.agent.guards.grounding import (
    checker_input,
    numbers,
    repair_note,
    unsupported_numbers,
)
from app.agent.memory import apply_summary, goal_from_events, merge_goal, summarizer_input
from app.agent.phrases import lang_key, phrase
from app.agent.registry import Registry, Source, ToolContext, ToolRuntime
from app.agent.schemas import CheckResult, GuardVerdict, RouteDecision, Summary
from app.agent.skills_loader import TurnFacts, available_for_router, load_skills, select
from app.agent.state import AgentState
from app.core.models_registry import NodeKey, spec_for
from app.core.tenancy import tenant_session
from app.kb.embeddings import EmbeddingProvider
from app.llm.base import LLMProvider
from app.llm.claude import (
    CassetteMissingError,
    LLMError,
    PrefixViolationError,
    RefusalError,
    ToolStartHook,
    TurnPrefixGuard,
)
from app.llm.runs import run_record, to_row
from app.models.conversations import Conversation, Message
from app.prompts import load_prompt, render_tenant_block

log = structlog.get_logger(__name__)

HISTORY_KEEP = 2 * ctxb.HISTORY_TURNS
LOW_CONFIDENCE = 0.6
WA_MAX = 4096
CTA = {
    "school": {
        "en": "Book a campus visit",
        "roman_ur": "Campus visit book karein",
        "ur": "کیمپس وزٹ بک کریں",
    },
    "college": {
        "en": "Book a counselling session",
        "roman_ur": "Counselling session book karein",
        "ur": "کاؤنسلنگ سیشن بک کریں",
    },
    "university": {
        "en": "How do I apply?",
        "roman_ur": "Apply kaise karein?",
        "ur": "اپلائی کیسے کریں؟",
    },
}


@dataclass
class AgentDeps:
    sessionmaker: async_sessionmaker[AsyncSession]
    llm: LLMProvider
    registry: Registry
    embedder: EmbeddingProvider | None = None
    redis: Any = None
    check_prefix: bool = True  # TurnPrefixGuard (dev/test assert; cheap, kept on in prod too)
    status_hooks: dict[str, ToolStartHook] = field(default_factory=dict)  # thread_id → hook


def soft_error(exc: BaseException) -> bool:
    """LLM failures that degrade to a safe default; programming/replay errors propagate."""
    if isinstance(exc, CassetteMissingError | PrefixViolationError):
        return False
    return isinstance(exc, LLMError | anthropic.APIError | TimeoutError)


def cached_system(prompt_name: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": load_prompt(prompt_name).text, "cache_control": ctxb.CACHE}]


def guard_user_content(recent: str, message: str) -> str:
    head = f"<recent_history>\n{recent}\n</recent_history>\n" if recent else ""
    return f"{head}<new_message>\n{message}\n</new_message>"


def router_user_content(
    institution_type: str, skills: list[str], summary: str, recent: str, message: str
) -> str:
    parts = (
        f"<institution_type>{institution_type}</institution_type>",
        f"<available_skills>{', '.join(skills)}</available_skills>",
        f"<summary>\n{summary}\n</summary>" if summary else "",
        f"<recent_history>\n{recent}\n</recent_history>" if recent else "",
        f"<new_message>\n{message}\n</new_message>",
    )
    return "\n".join(p for p in parts if p)


def finalize_route(route: RouteDecision, skills: list[str]) -> RouteDecision:
    """Deterministic post-processing of the router output (also used by the router eval)."""
    route.skills = [s for s in route.skills if s in skills]
    route.search_queries = [q for q in route.search_queries if q.strip()][:3]
    route.intents = route.intents[:3] or ["other"]
    if route.confidence < LOW_CONFIDENCE or route.module == "fees":
        route.complexity = "complex"
    return route


def _uuid(state: AgentState, key: str) -> uuid.UUID:
    return uuid.UUID(str(state[key]))  # type: ignore[literal-required]


def _now(state: AgentState) -> dt.datetime:
    return dt.datetime.fromisoformat(state["now"])


def _recent(state: AgentState, turns: int) -> str:
    return ctxb.history_text(state.get("history", [])[-2 * turns :], budget=600)


def failed_run(node: NodeKey, exc: BaseException, prompt_hash: str | None) -> dict[str, Any]:
    return run_record(
        node,
        error=f"{type(exc).__name__}: {exc}",
        model=spec_for(node).model,
        prompt_hash=prompt_hash,
    )


def pick_citations(
    text: str, sources: list[dict[str, Any]], check: dict[str, Any] | None, limit: int = 3
) -> list[dict[str, Any]]:
    """Sources the reply relied on: those the checker matched, else those sharing numbers or
    several words with the reply. One per (document, page)."""
    supported = [c.get("source_id") for c in (check or {}).get("claims", []) if c.get("supported")]
    chosen = [s for s in sources if s["id"] in supported]
    if not chosen:
        reply_nums = numbers(text)
        reply_words = {w for w in re.findall(r"\w{4,}", text.lower())}

        def score(s: dict[str, Any]) -> int:
            words = {w for w in re.findall(r"\w{4,}", s["text"].lower())}
            return 3 * len(reply_nums & numbers(s["text"])) + len(reply_words & words)

        chosen = [s for s in sorted(sources, key=score, reverse=True) if score(s) >= 3]
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    for s in chosen:
        cit = s.get("citation")
        if not cit:
            continue
        key = (cit["document_id"], cit.get("page"))
        if key not in seen:
            seen.add(key)
            out.append(cit)
        if len(out) == limit:
            break
    return out


def citation_label(cit: dict[str, Any]) -> str:
    return f"{cit['title']}, p. {cit['page']}" if cit.get("page") else str(cit["title"])


def format_reply(text: str, channel: str, language: str, citations: list[dict[str, Any]]) -> str:
    """Channel formatting (deterministic). WhatsApp: no tables/headings, *bold*, ≤ 4096 chars,
    short source line, RTL mark for Urdu. Widget: markdown; citations travel as chips."""
    if channel != "whatsapp":
        return text.strip()
    out = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    out = re.sub(r"^#{1,6}\s*", "", out, flags=re.M)
    out = "\n".join(line for line in out.splitlines() if not re.match(r"^\s*\|", line)).strip()
    if citations:
        prefix = "ماخذ: " if language == "ur" else "Source: "
        out += "\n\n" + prefix + "; ".join(citation_label(c) for c in citations)
    if language == "ur":
        out = "‏" + out
    return out[:WA_MAX]


def build_graph(
    deps: AgentDeps, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[AgentState, Any, AgentState, AgentState]:
    async def guard_in(state: AgentState) -> dict[str, Any]:
        text = state["inbound"]["text"]
        runs = list(state.get("runs", []))
        guess = detect_language(text)
        prompt = load_prompt("guard_in")
        if injection_prefilter(text):
            verdict = GuardVerdict(
                language=guess,
                injection=True,
                abuse=False,
                pii_request=False,
                off_topic=False,
                reason="injection pattern (pre-filter)",
            )
        else:
            user = guard_user_content(_recent(state, 2), text)
            try:
                res = await deps.llm.parse(
                    "guard_in",
                    system=cached_system("guard_in"),
                    messages=[{"role": "user", "content": user}],
                    output_format=GuardVerdict,
                )
                verdict = res.output
                runs.append(run_record("guard_in", res, prompt_hash=prompt.hash))
            except Exception as exc:
                if not soft_error(exc):
                    raise
                verdict = GuardVerdict.safe_default(guess)
                runs.append(failed_run("guard_in", exc, prompt.hash))
        language = verdict.language
        preferred = state.get("contact", {}).get("preferred_language")
        if language == "en" and preferred in ("ur", "roman_ur") and len(text.split()) <= 2:
            language = preferred  # "ok", "fee?" — keep the contact's language
        return {"guard": verdict.model_dump(), "language": language, "runs": runs}

    def after_guard(state: AgentState) -> str:
        g = GuardVerdict.model_validate(state["guard"])
        return "safe_reply" if g.blocked or g.off_topic else "router"

    async def safe_reply(state: AgentState) -> dict[str, Any]:
        g = GuardVerdict.model_validate(state["guard"])
        kind = "blocked" if g.blocked else "off_topic"
        return {"final": phrase(kind, state["language"]), "reply_kind": "blocked"}

    async def router(state: AgentState) -> dict[str, Any]:
        runs = list(state.get("runs", []))
        tenant = state["tenant"]
        prompt = load_prompt("router")
        skills = available_for_router(tenant["type"])
        user = router_user_content(
            tenant["type"],
            skills,
            ctxb.summary_text(state.get("summary")),
            _recent(state, 2),
            state["inbound"]["text"],
        )
        try:
            res = await deps.llm.parse(
                "router",
                system=cached_system("router"),
                messages=[{"role": "user", "content": user}],
                output_format=RouteDecision,
            )
            route = res.output
            runs.append(run_record("router", res, prompt_hash=prompt.hash))
        except Exception as exc:
            if not soft_error(exc):
                raise
            route = RouteDecision.safe_default()
            runs.append(failed_run("router", exc, prompt.hash))
        return {"route": finalize_route(route, skills).model_dump(), "runs": runs}

    async def load_context(state: AgentState) -> dict[str, Any]:
        route = RouteDecision.model_validate(state["route"])
        tenant = state["tenant"]
        contact = state.get("contact", {})
        module = route.module
        skills = select(
            TurnFacts(
                institution_type=tenant["type"],
                module="admissions" if module == "general" else module,
                intents=tuple(route.intents),
                channel=state["channel"],
                language=state["language"],
                requested=tuple(route.skills),
            )
        )
        if module == "general":  # greetings etc.: no institution-type pack, keep style guides
            skills = [s for s in skills if not s.name.startswith("admissions-")]
        node: NodeKey = "agent_complex" if route.complexity == "complex" else "agent_simple"
        tenant_block = render_tenant_block(
            {
                "name": tenant["name"],
                "type": tenant["type"],
                "city": tenant["city"],
                "languages": tenant["languages"],
                "academic_year": tenant.get("academic_year"),
                "cta": tenant["cta"],
                "details": tenant["details"],
                "facts_version": tenant["facts_version"],
            }
        )
        history = ctxb.reset_history_if_idle(
            state.get("history", []), state.get("last_turn_at"), _now(state)
        )
        turn = ctxb.turn_context(
            now=_now(state),
            timezone=tenant["timezone"],
            academic_year=tenant.get("academic_year"),
            channel=state["channel"],
            language=state["language"],
            verified=bool(contact.get("verified")),
            contact=contact.get("profile_view", {}),
        )
        return {
            "history": history,
            "context": {
                "module": module,
                "node": node,
                "tenant_block": tenant_block,
                "skills": [s.name for s in skills],
                "turn": turn,
            },
        }

    async def agent(state: AgentState) -> dict[str, Any]:
        c = state["context"]
        module, node = c["module"], c["node"]
        tenant = state["tenant"]
        contact = state.get("contact", {})
        skills_by_name = load_skills()
        skills = [skills_by_name[n] for n in c["skills"] if n in skills_by_name]
        req = ctxb.build_agent_request(
            module=module,
            tenant_block=c["tenant_block"],
            skills=skills,
            tools=deps.registry.definitions(module),
            turn=c["turn"],
            summary=state.get("summary"),
            history=state.get("history", []),
            message=state["inbound"]["text"],
        )
        prior = state.get("check")
        repairing = prior is not None and state.get("repairs", 0) == 0
        messages = list(state.get("turn_messages") or req.messages)
        if prior is not None and repairing:
            check = CheckResult.model_validate(prior["llm"])
            note = repair_note(check, prior["numbers"], prior["script_ok"])
            messages = ctxb.append_operator_note(messages, note)
        runs = list(state.get("runs", []))
        tool_calls = list(state.get("tool_calls", []))
        tool_outputs = list(state.get("tool_outputs", []))
        tctx = ToolContext(
            institution_id=_uuid(state, "institution_id"),
            contact_id=_uuid(state, "contact_id"),
            conversation_id=_uuid(state, "conversation_id"),
            channel=state["channel"],
            verified=bool(contact.get("verified")),
            institution_type=tenant["type"],
            timezone=tenant["timezone"],
            now=_now(state),
            sources=[Source(**s) for s in state.get("sources", [])],
            events=list(state.get("events", [])),
        )
        runtime = ToolRuntime(sessionmaker=deps.sessionmaker, embedder=deps.embedder)
        guard = TurnPrefixGuard() if deps.check_prefix else None
        hook = deps.status_hooks.get(f"{state['institution_id']}:{state['contact_id']}")
        draft: str | None = None
        reply_kind = "answer"
        final: str | None = None
        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                result = await deps.llm.complete(
                    node,
                    system=req.system,
                    messages=messages,
                    tools=req.tools,
                    prefix_guard=guard,
                    on_tool_start=hook,
                )
            except RefusalError as exc:
                runs.append(failed_run(node, exc, req.prompt_hash))
                reply_kind, final = "fallback", phrase("fallback", state["language"])
                break
            except Exception as exc:
                if not soft_error(exc):
                    raise
                log.warning("agent.llm_failed", error=str(exc))
                runs.append(failed_run(node, exc, req.prompt_hash))
                reply_kind, final = "error", phrase("error", state["language"])
                break
            runs.append(run_record(node, result, prompt_hash=req.prompt_hash, skills=req.skills))
            messages.append({"role": "assistant", "content": result.content})
            uses = result.tool_uses
            if result.stop_reason != "tool_use" or not uses:
                draft = result.text or None
                break
            if iteration == MAX_TOOL_ITERATIONS - 1:
                break  # G13 loop cap: at most 6 model calls per agent pass
            outcomes = await deps.registry.execute_all(
                [(u.id, u.name, u.input) for u in uses], tctx, runtime, module=module
            )
            messages.append(ctxb.tool_results_message([o.block() for o in outcomes]))
            for use, outcome in zip(uses, outcomes, strict=True):
                tool_calls.append(outcome.trace(use.input))
                tool_outputs.append(
                    {"name": use.name, "content": outcome.content, "is_error": outcome.is_error}
                )
        if final is None and draft is None:
            reply_kind, final = "fallback", phrase("fallback", state["language"])
        return {
            "turn_messages": messages,
            "runs": runs,
            "tool_calls": tool_calls,
            "tool_outputs": tool_outputs,
            "sources": [s.as_dict() for s in tctx.sources],
            "events": tctx.events,
            "draft": draft,
            "final": final,
            "reply_kind": reply_kind,
            "repairs": state.get("repairs", 0) + (1 if repairing else 0),
        }

    def after_agent(state: AgentState) -> str:
        if any(e["type"] == "handoff" for e in state.get("events", [])):
            return "handoff"
        if state.get("reply_kind") != "answer":
            return "compose"
        return "answer_check"

    async def answer_check(state: AgentState) -> dict[str, Any]:
        draft = state["draft"] or ""
        runs = list(state.get("runs", []))
        prompt = load_prompt("answer_check")
        corpus = [s["text"] for s in state.get("sources", [])]
        corpus += [t["content"] for t in state.get("tool_outputs", []) if not t.get("is_error")]
        corpus += [state["inbound"]["text"], state["context"]["turn"]]
        corpus.append(state["context"]["tenant_block"])
        corpus += [h["text"] for h in state.get("history", []) if h["role"] == "user"]
        missing = unsupported_numbers(draft, corpus)
        script = script_ok(state["language"], draft)
        contact = state.get("contact", {})
        try:
            res = await deps.llm.parse(
                "answer_check",
                system=cached_system("answer_check"),
                messages=[
                    {
                        "role": "user",
                        "content": checker_input(
                            draft=draft,
                            sources=state.get("sources", []),
                            tool_outputs=state.get("tool_outputs", []),
                            language=state["language"],
                            module=state["context"]["module"],
                            verified=bool(contact.get("verified")),
                            profile=state["context"]["tenant_block"],
                        ),
                    }
                ],
                output_format=CheckResult,
            )
            llm = res.output
            runs.append(run_record("answer_check", res, prompt_hash=prompt.hash))
        except Exception as exc:
            if not soft_error(exc):
                raise
            llm = CheckResult.fail_safe("checker unavailable")
            runs.append(failed_run("answer_check", exc, prompt.hash))
        ok = llm.ok and not llm.identity_leak and not missing and script
        return {
            "check": {"ok": ok, "llm": llm.model_dump(), "numbers": missing, "script_ok": script},
            "runs": runs,
        }

    def after_check(state: AgentState) -> str:
        if state["check"] and state["check"]["ok"]:
            return "compose"
        return "agent" if state.get("repairs", 0) == 0 else "safe_fallback"

    async def safe_fallback(state: AgentState) -> dict[str, Any]:
        return {"final": phrase("fallback", state["language"]), "reply_kind": "fallback"}

    async def handoff(state: AgentState) -> dict[str, Any]:
        event = next(e for e in state.get("events", []) if e["type"] == "handoff")
        async with tenant_session(deps.sessionmaker, _uuid(state, "institution_id")) as session:
            conv = await session.get(Conversation, _uuid(state, "conversation_id"))
            if conv is not None:
                conv.mode = "human"
                conv.status = "pending"
                if event.get("urgency") == "high":
                    conv.flagged = True
        return {"final": phrase("handoff", state["language"]), "reply_kind": "handoff"}

    async def compose(state: AgentState) -> dict[str, Any]:
        kind = state.get("reply_kind", "answer")
        text = (state.get("final") if kind != "answer" else state.get("draft")) or ""
        citations = (
            pick_citations(text, state.get("sources", []), (state.get("check") or {}).get("llm"))
            if kind == "answer"
            else []
        )
        route = state.get("route") or {}
        quick: list[str] = []
        if (
            kind == "answer"
            and route.get("module") == "admissions"
            and state["channel"] == "widget"
        ):
            cta = CTA.get(state["tenant"]["type"], {})
            if cta and not any(e["type"] == "booked" for e in state.get("events", [])):
                quick = [cta[lang_key(state["language"])]]
        return {
            "final": format_reply(text, state["channel"], state["language"], citations),
            "citations": citations,
            "quick_replies": quick,
        }

    async def persist(state: AgentState) -> dict[str, Any]:
        inst = _uuid(state, "institution_id")
        conv_id = _uuid(state, "conversation_id")
        async with tenant_session(deps.sessionmaker, inst) as session:
            rows = [to_row(inst, r, conv_id) for r in state.get("runs", [])]
            session.add_all(rows)
            await session.flush()
            agent_runs = [r for r in rows if r.node.startswith("agent")]
            conv = await session.get(Conversation, conv_id)
            if conv is None:
                raise LookupError("conversation vanished")
            check = state.get("check")
            failed_check = check is not None and not check["ok"]
            if state.get("reply_kind") == "fallback" and failed_check:
                conv.flagged = True  # admin "Flagged answers" queue
            msg = Message(
                conversation_id=conv_id,
                direction="out",
                sender="ai",
                type="text",
                text=state.get("final"),
                status="queued",
                citations=state.get("citations") or None,
                tool_calls=state.get("tool_calls") or None,
                llm_run_id=agent_runs[-1].id if agent_runs else None,
            )
            session.add(msg)
            conv.updated_at = _now(state)
            await session.flush()
            message_id = str(msg.id)
        history = list(state.get("history", []))
        history.append({"role": "user", "text": state["inbound"]["text"]})
        history.append(
            {
                "role": "assistant",
                "text": state.get("final") or "",
                "tools": ctxb.collapse_tools(state.get("tool_calls", [])),
            }
        )
        return {
            "outbound_message_id": message_id,
            "history": history[-HISTORY_KEEP:],
            "last_turn_at": state["now"],
        }

    def after_persist(state: AgentState) -> str:
        return "summarize" if state.get("reply_kind") in ("answer", "fallback", "handoff") else END

    async def summarize(state: AgentState) -> dict[str, Any]:
        inst = _uuid(state, "institution_id")
        prompt = load_prompt("summarizer")
        contact = state.get("contact", {})
        events = state.get("events", [])
        goal = merge_goal(
            state.get("goal_status"),
            goal_from_events(events, answered=state.get("reply_kind") == "answer"),
        )
        user = summarizer_input(
            previous=state.get("summary"),
            verified=bool(contact.get("verified")),
            user_text=state["inbound"]["text"],
            reply=state.get("final") or "",
            tools_line=ctxb.collapse_tools(state.get("tool_calls", [])),
            events=events,
            staff_notes=state.get("staff_notes") or None,
        )
        summary: Summary | None = None
        try:
            res = await deps.llm.parse(
                "summarizer",
                system=cached_system("summarizer"),
                messages=[{"role": "user", "content": user}],
                output_format=Summary,
            )
            summary = res.output
            record = run_record("summarizer", res, prompt_hash=prompt.hash)
        except Exception as exc:
            if not soft_error(exc):
                raise
            record = failed_run("summarizer", exc, prompt.hash)
        contact_text = "\n".join(
            [h["text"] for h in state.get("history", []) if h["role"] == "user"]
        )
        async with tenant_session(deps.sessionmaker, inst) as session:
            session.add(to_row(inst, record, _uuid(state, "conversation_id")))
            if summary is not None:
                await apply_summary(
                    session,
                    contact_id=_uuid(state, "contact_id"),
                    conversation_id=_uuid(state, "conversation_id"),
                    channel=state["channel"],
                    summary=summary,
                    goal_status=goal,
                    contact_text=contact_text,
                )
        out: dict[str, Any] = {"goal_status": goal}
        if summary is not None:
            out["summary"] = {**summary.model_dump(mode="json"), "goal_status": goal}
        return out

    def after_summarize(state: AgentState) -> str:
        return "await_staff" if state.get("reply_kind") == "handoff" else END

    async def await_staff(state: AgentState) -> dict[str, Any]:
        resume = interrupt(
            {"type": "handoff", "conversation_id": state["conversation_id"]}
        )  # paused until "Return to AI" → Command(resume={"staff_note": ...})
        note = (resume or {}).get("staff_note") if isinstance(resume, dict) else None
        if not note:
            return {}
        history = [*state.get("history", []), {"role": "staff", "text": note}]
        return {
            "staff_notes": [*state.get("staff_notes", []), note],
            "history": history[-HISTORY_KEEP:],
        }

    g: StateGraph[AgentState, Any, AgentState, AgentState] = StateGraph(AgentState)
    nodes: dict[str, Callable[..., Any]] = {
        "guard_in": guard_in,
        "safe_reply": safe_reply,
        "router": router,
        "load_context": load_context,
        "agent": agent,
        "answer_check": answer_check,
        "safe_fallback": safe_fallback,
        "handoff": handoff,
        "compose": compose,
        "persist": persist,
        "summarize": summarize,
        "await_staff": await_staff,
    }
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "guard_in")
    g.add_conditional_edges("guard_in", after_guard, ["safe_reply", "router"])
    g.add_edge("safe_reply", "compose")
    g.add_edge("router", "load_context")
    g.add_edge("load_context", "agent")
    g.add_conditional_edges("agent", after_agent, ["handoff", "compose", "answer_check"])
    g.add_conditional_edges("answer_check", after_check, ["compose", "agent", "safe_fallback"])
    g.add_edge("safe_fallback", "compose")
    g.add_edge("handoff", "compose")
    g.add_edge("compose", "persist")
    g.add_conditional_edges("persist", after_persist, ["summarize", END])
    g.add_conditional_edges("summarize", after_summarize, ["await_staff", END])
    g.add_edge("await_staff", END)
    return g.compile(checkpointer=checkpointer)
