"""Step 5.4.5 — the takeover invariant end-to-end (FakeLLM, zero spend): AI replies → staff take
over → the parent's next message gets NO AI reply → staff reply reaches the widget poll (I-18) →
return to AI with a note → the next AI turn sees the staff line in its context."""

import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import AgentDeps, build_graph
from app.agent.runtime import AgentRuntime
from app.agent.tools import build_registry
from app.core.config import Settings
from app.kb.embeddings import make_provider
from app.llm.fake import FakeLLM, text_reply, tool_call
from app.models.core import Institution
from app.services import provisioning
from tests.integration.test_graph import FEE_CALL, GOOD, script
from tests.integration.test_tools_admissions import ingest_fees
from tests.integration.test_widget_api import ORIGIN, events
from tests.support import PASSWORD, Factory, as_admin, auth_headers

pytestmark = pytest.mark.integration
SECOND = "Ji, campus visit ke liye Saturday 10 baje ka slot available hai."


def test_takeover_staff_reply_and_return_to_ai(
    client: TestClient, factory: Factory, it_settings: Settings
) -> None:
    tenant: uuid.UUID = ingest_fees(client, factory, it_settings)

    async def slug_of(session: AsyncSession) -> str:
        inst = await session.get(Institution, tenant)
        assert inst is not None
        return inst.slug

    slug: str = asyncio.run(as_admin(it_settings, slug_of))
    llm = FakeLLM(script(agent_simple=[tool_call(*FEE_CALL), text_reply(GOOD), text_reply(SECOND)]))
    deps = AgentDeps(
        sessionmaker=client.app.state.resources.sessionmaker,  # type: ignore[attr-defined]
        llm=llm,
        registry=build_registry(),
        embedder=make_provider(it_settings),
    )
    client.app.state.agent.set(AgentRuntime(deps, build_graph(deps, InMemorySaver())))  # type: ignore[attr-defined]

    s = client.post("/api/v1/widget/sessions", json={"slug": slug}, headers={"Origin": ORIGIN})
    sess = s.json()
    wh = {"Authorization": f"Bearer {sess['token']}", "Origin": ORIGIN}
    base = f"/api/v1/widget/sessions/{sess['session_id']}"

    def say(text: str) -> list[tuple[str, dict[str, Any]]]:
        r = client.post(f"{base}/messages", json={"text": text, "lang": "en"}, headers=wh)
        return events(r.text)

    assert any(e == "message" and d["text"] == GOOD for e, d in say("Class 3 ki fee?"))

    # staff view: one widget conversation, AI mode
    staff = auth_headers(client, staff_email(factory, tenant), tenant)
    convs = client.get("/api/v1/conversations", headers=staff).json()
    assert len(convs) == 1 and convs[0]["mode"] == "ai"
    cid = convs[0]["id"]

    r = client.post(f"/api/v1/conversations/{cid}/takeover", headers=staff)
    assert r.status_code == 200 and r.json()["mode"] == "human"

    agent_calls = llm.nodes_called().count("agent_simple")
    evs = say("Mujhe kisi insaan se baat karni hai")
    assert [e for e, _ in evs if e == "message"] == []  # no AI reply while staff own the chat
    assert evs[-1] == ("done", {"status": "human_mode", "human": True})
    assert llm.nodes_called().count("agent_simple") == agent_calls

    r = client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"text": "Salam, main Nadia hoon."},
        headers=staff,
    )
    assert r.status_code == 201
    up = client.get(f"{base}/updates", params={"after": 0}, headers=wh).json()
    assert up["mode"] == "human"
    assert [m["text"] for m in up["messages"]] == ["Salam, main Nadia hoon."]
    seq = up["messages"][-1]["seq"]
    note = client.post(f"/api/v1/conversations/{cid}/notes", json={"text": "VIP"}, headers=staff)
    assert note.status_code == 201
    later = client.get(f"{base}/updates", params={"after": seq}, headers=wh).json()
    assert later["messages"] == []  # internal notes never reach the parent

    r = client.post(
        f"/api/v1/conversations/{cid}/return-to-ai",
        json={"note": "Promised a Saturday visit"},
        headers=staff,
    )
    assert r.status_code == 200 and r.json()["mode"] == "ai"

    evs = say("Visit kab ho sakta hai?")
    assert any(e == "message" and d["text"] == SECOND for e, d in evs)
    last_agent = [c for c in llm.calls if c["node"] == "agent_simple"][-1]
    assert "Promised a Saturday visit" in json.dumps(last_agent["messages"])

    msgs = client.get(f"/api/v1/conversations/{cid}/messages", headers=staff).json()
    kinds = [(m["sender"], m["type"]) for m in msgs]
    assert ("staff", "text") in kinds and ("staff", "note") in kinds
    assert kinds.count(("system", "note")) == 2  # took over / returned


def staff_email(factory: Factory, tenant: uuid.UUID) -> str:
    """A staff-role member of `tenant` (the inbox is a staff+ page)."""
    email = f"staff-{uuid.uuid4().hex[:6]}@raabta-test.pk"

    async def make(session: AsyncSession) -> str:
        user = await provisioning.upsert_user(session, email=email, name="Nadia", password=PASSWORD)
        await provisioning.upsert_membership(
            session, institution_id=tenant, user_id=user.id, role="staff"
        )
        return email

    return asyncio.run(as_admin(factory.settings, make))
