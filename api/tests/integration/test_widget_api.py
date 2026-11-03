"""Step 4.1 — the one invariant worth a CI test (D-11 check-then-send): a draft that fails
`answer_check` never reaches the SSE stream; an approved one arrives after the tool status
events. Everything else is covered by `scripts.widget_smoke` + the browser e2e (p4_s1/p4_s3)."""

import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import AgentDeps, build_graph
from app.agent.phrases import phrase
from app.agent.runtime import AgentRuntime
from app.agent.tools import build_registry
from app.core.config import Settings
from app.kb.embeddings import make_provider
from app.llm.fake import FakeLLM, text_reply, tool_call
from app.models.core import Institution
from tests.integration.test_graph import FEE_CALL, GOOD, check, script
from tests.integration.test_tools_admissions import ingest_fees
from tests.support import Factory, as_admin

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:3000"
DRAFT = "Class 3 fee is PKR 99,999 (SECRET-DRAFT)."


def events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def chat(client: TestClient, slug: str, text: str) -> list[tuple[str, dict[str, Any]]]:
    s = client.post("/api/v1/widget/sessions", json={"slug": slug}, headers={"Origin": ORIGIN})
    assert s.status_code == 201, s.text
    body = s.json()
    r = client.post(
        f"/api/v1/widget/sessions/{body['session_id']}/messages",
        json={"text": text, "lang": "en"},
        headers={"Authorization": f"Bearer {body['token']}", "Origin": ORIGIN},
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return events(r.text)


@pytest.mark.parametrize("approved", [True, False])
def test_check_then_send(
    client: TestClient, factory: Factory, it_settings: Settings, approved: bool
) -> None:
    tenant: uuid.UUID = ingest_fees(client, factory, it_settings)

    async def slug_of(session: AsyncSession) -> str:
        inst = await session.get(Institution, tenant)
        assert inst is not None
        return inst.slug

    slug: str = asyncio.run(as_admin(it_settings, slug_of))
    reply = GOOD if approved else DRAFT
    llm = FakeLLM(
        script(
            agent_simple=[tool_call(*FEE_CALL), text_reply(reply)],
            answer_check=check(ok=approved, fixes=() if approved else ("unsupported fee",)),
        )
    )
    deps = AgentDeps(
        sessionmaker=client.app.state.resources.sessionmaker,  # type: ignore[attr-defined]
        llm=llm,
        registry=build_registry(),
        embedder=make_provider(it_settings),
    )
    client.app.state.agent.set(AgentRuntime(deps, build_graph(deps, InMemorySaver())))  # type: ignore[attr-defined]

    evs = chat(client, slug, "Class 3 ki fee kitni hai?")
    names = [e for e, _ in evs]
    assert names[0] == "status" and names[-1] == "done"
    assert names.count("message") == 1
    msg_at = names.index("message")
    assert all(i < msg_at for i, n in enumerate(names) if n == "status")
    assert any(d.get("tool") == "get_fee_table" for e, d in evs[:msg_at] if e == "status")
    msg = evs[msg_at][1]
    if approved:
        assert msg["text"] == GOOD and msg["kind"] == "answer"
    else:
        assert msg["kind"] == "fallback" and msg["text"] == phrase("fallback", msg["language"])
        assert "SECRET-DRAFT" not in json.dumps(evs) and "99,999" not in json.dumps(evs)
