"""Step 3.10 — scripted demo conversation through the chat CLI runner (scripted LLM, seeded test
DB): transcript shows route, tools, check verdict and citations; expected-tool check works."""

from pathlib import Path

import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.agent.graph import AgentDeps, build_graph
from app.agent.tools import build_registry
from app.core.config import Settings
from app.db.session import make_sessionmaker
from app.kb.embeddings import make_provider
from app.llm.fake import FakeLLM, text_reply, tool_call
from evals.run_evals import institution_ids
from scripts.chat import missing_tools, render_transcript, run_conversation
from tests.integration.test_eval_harness import SUMMARY
from tests.integration.test_graph import check, guard_ok, route

pytestmark = pytest.mark.integration
SCRIPTS = Path(__file__).resolve().parents[3] / "docs" / "demo" / "scripts.yaml"


async def test_scripted_conversation_transcript(it_settings: Settings) -> None:
    convs = yaml.safe_load(SCRIPTS.read_text(encoding="utf-8"))["conversations"]
    assert len(convs) == 9 and {c["language"] for c in convs} == {"en", "ur", "roman_ur"}
    conv = {**next(c for c in convs if c["id"] == "school-en"), "turns": ["admission fee?"]}
    engine = create_async_engine(it_settings.database_url, poolclass=NullPool)
    try:
        sm = make_sessionmaker(engine)
        ids = await institution_ids(sm, {conv["institution"]})
        if not ids:
            pytest.skip("demo institutions not seeded in the test DB")
        llm = FakeLLM(
            {
                "guard_in": guard_ok("en"),
                "router": route(),
                "agent_simple": [
                    tool_call("get_fee_table", {"program_or_class": None, "academic_year": None}),
                    text_reply(
                        "The admission fee is PKR 25,000 and the security deposit PKR 20,000."
                    ),
                ],
                "answer_check": check(True),
                "summarizer": SUMMARY,
            }
        )
        deps = AgentDeps(
            sessionmaker=sm, llm=llm, registry=build_registry(), embedder=make_provider(it_settings)
        )
        turns = await run_conversation(
            deps, build_graph(deps, InMemorySaver()), ids[conv["institution"]], conv, "demo-test"
        )
    finally:
        await engine.dispose()
    md = render_transcript(conv, turns)
    assert md.startswith("# Demo — school-en (abc-grammar-school, widget, en)")
    assert "**Assistant:** The admission fee is PKR 25,000" in md
    assert "tools: get_fee_table" in md and "check: pass" in md and "sources: " in md
    assert "sources: —" not in md
    assert missing_tools(conv, turns) == ["get_scholarships", "search_knowledge"]
