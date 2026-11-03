"""Local chat CLI over `run_inbound` (step 3.10) — the same graph the widget/WhatsApp use.

  uv run python -m scripts.chat --institution abc-grammar-school --lang roman_ur
  uv run python -m scripts.chat --script ../docs/demo/scripts.yaml --mode live --out ../docs/demo

Shows per turn: route, tools, check verdict, citations and cost. Uses DATABASE_URL (run
`make seed` + `make ingest-seeds` first) and EMBEDDING_PROVIDER from .env. `--mode live|record`
spends tokens; `replay` serves cassettes; the clock is frozen at EVAL_NOW for scripted runs so
cassettes stay replayable."""

import argparse
import asyncio
import datetime as dt
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import AgentDeps, build_graph, citation_label
from app.agent.inbound import InboundEvent, TurnResult, run_inbound
from app.agent.tools import build_registry
from app.core.config import get_settings
from app.db.session import make_engine, make_sessionmaker
from app.kb.embeddings import make_provider
from app.llm.base import LLMProvider
from evals.run_evals import EVAL_NOW, institution_ids, make_llm


@dataclass
class Turn:
    user: str
    result: TurnResult


def turn_lines(t: Turn) -> list[str]:
    r = t.result
    route = r.route or {}
    tools = (
        ", ".join(f"{c['name']}{' ✘' if c.get('is_error') else ''}" for c in r.tool_calls) or "—"
    )
    check = r.check or {}
    verdict = "pass" if check.get("ok") else ("fail" if check else "—")
    cites = "; ".join(citation_label(c) for c in r.citations) or "—"
    return [
        f"**User:** {t.user}",
        "",
        f"**Assistant:** {r.reply or '(no reply: ' + r.status + ')'}",
        "",
        f"<sub>route: {route.get('module', '—')}/{','.join(route.get('intents', []))}/"
        f"{route.get('complexity', '—')} · tools: {tools} · check: {verdict} · "
        f"kind: {r.reply_kind} · sources: {cites} · cost: ${r.cost_usd:.4f}</sub>",
        "",
    ]


def render_transcript(conv: dict[str, Any], turns: list[Turn]) -> str:
    total = sum((t.result.cost_usd for t in turns), start=type(turns[0].result.cost_usd)(0))
    head = [
        f"# Demo — {conv['id']} ({conv['institution']}, {conv['channel']}, {conv['language']})",
        "",
        f"Clock frozen at {EVAL_NOW.isoformat()} · total cost ${total:.4f}",
        "",
    ]
    return "\n".join(head + [line for t in turns for line in turn_lines(t)])


def missing_tools(conv: dict[str, Any], turns: list[Turn]) -> list[str]:
    called = {c["name"] for t in turns for c in t.result.tool_calls if not c.get("is_error")}
    return [t for t in conv.get("expect_tools", []) if t not in called]


async def run_conversation(
    deps: AgentDeps, graph: Any, institution_id: uuid.UUID, conv: dict[str, Any], visitor: str
) -> list[Turn]:
    turns: list[Turn] = []
    for i, text in enumerate(conv["turns"]):
        result = await run_inbound(
            deps,
            graph,
            InboundEvent(
                institution_id=institution_id,
                channel=conv.get("channel", "widget"),
                text=text,
                widget_visitor_id=visitor,
                now=EVAL_NOW + dt.timedelta(minutes=i),
            ),
        )
        turns.append(Turn(text, result))
    return turns


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    llm: LLMProvider = make_llm(args.mode)
    engine = make_engine(settings.database_url)
    deps = AgentDeps(
        sessionmaker=make_sessionmaker(engine),
        llm=llm,
        registry=build_registry(),
        embedder=make_provider(settings),
    )
    graph = build_graph(deps, InMemorySaver())
    rc = 0
    try:
        if args.script:
            convs: list[dict[str, Any]] = args.conversations
            ids = await institution_ids(deps.sessionmaker, {c["institution"] for c in convs})
            for conv in convs:
                if args.only and conv["id"] not in args.only.split(","):
                    continue
                turns = await run_conversation(
                    deps, graph, ids[conv["institution"]], conv, f"demo-{conv['id']}"
                )
                text = render_transcript(conv, turns)
                if args.out:
                    out = Path(args.out) / f"{conv['id']}.md"
                    out.write_text(text + "\n", encoding="utf-8")
                    print("wrote", out)
                else:
                    print(text)
                gaps = missing_tools(conv, turns)
                if gaps:
                    print(f"✘ {conv['id']}: expected tools not called: {gaps}")
                    rc = 1
            return rc
        ids = await institution_ids(deps.sessionmaker, {args.institution})
        if args.institution not in ids:
            raise SystemExit(f"unknown institution {args.institution} (run make seed)")
        visitor = args.visitor or f"cli-{uuid.uuid4().hex[:8]}"
        print(f"Chatting with {args.institution} as {visitor} ({args.mode}). Ctrl-D to quit.")
        while True:
            try:
                text = (await asyncio.to_thread(input, "\nYou: ")).strip()
            except EOFError:
                return 0
            if not text:
                continue
            result = await run_inbound(
                deps,
                graph,
                InboundEvent(
                    institution_id=ids[args.institution],
                    channel=args.channel,
                    text=text,
                    widget_visitor_id=visitor,
                ),
            )
            print("\n".join(turn_lines(Turn(text, result))[2:]))
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.chat")
    p.add_argument("--institution", default="abc-grammar-school")
    p.add_argument("--lang", default="roman_ur", help="informational; the agent mirrors you")
    p.add_argument("--channel", choices=["widget", "whatsapp"], default="widget")
    p.add_argument("--mode", choices=["live", "record", "replay"], default="live")
    p.add_argument("--visitor", default=None)
    p.add_argument("--script", default=None, help="docs/demo/scripts.yaml")
    p.add_argument("--only", default=None, help="comma-separated conversation ids")
    p.add_argument("--out", default=None, help="directory for transcripts")
    args = p.parse_args(argv)
    if args.script:
        data = yaml.safe_load(Path(args.script).read_text(encoding="utf-8"))
        args.conversations = data["conversations"]
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
