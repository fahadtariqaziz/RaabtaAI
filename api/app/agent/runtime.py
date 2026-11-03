"""Process-wide agent runtime for the API (step 4.1): `AgentDeps` + compiled graph on the
Postgres checkpointer. Built lazily on the first chat turn (so non-chat routes and tests never
open the checkpointer pool) and closed in the app lifespan."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.agent.graph import AgentDeps, build_graph
from app.agent.inbound import postgres_checkpointer
from app.agent.tools import build_registry
from app.core.config import Settings
from app.core.resources import Resources
from app.kb.embeddings import make_provider
from app.llm.base import LLMProvider


@dataclass
class AgentRuntime:
    deps: AgentDeps
    graph: CompiledStateGraph[Any, Any, Any, Any]


def make_agent_llm(settings: Settings) -> LLMProvider:
    if settings.agent_llm == "demo":
        from app.llm.demo import demo_llm

        return demo_llm()
    from app.llm.claude import ClaudeClient

    return ClaudeClient(settings.require("anthropic_api_key"), mode="live")


class AgentRuntimeHolder:
    def __init__(self, settings: Settings, resources: Resources) -> None:
        self._settings = settings
        self._resources = resources
        self._lock = asyncio.Lock()
        self._stack = AsyncExitStack()
        self._runtime: AgentRuntime | None = None

    def set(self, runtime: AgentRuntime) -> None:
        """Tests inject a runtime (FakeLLM / in-memory checkpointer)."""
        self._runtime = runtime

    async def get(self) -> AgentRuntime:
        if self._runtime is not None:
            return self._runtime
        async with self._lock:
            if self._runtime is None:
                checkpointer = await self._stack.enter_async_context(
                    postgres_checkpointer(self._settings.database_url)
                )
                deps = AgentDeps(
                    sessionmaker=self._resources.sessionmaker,
                    llm=make_agent_llm(self._settings),
                    registry=build_registry(),
                    embedder=make_provider(self._settings),
                    redis=self._resources.redis,
                )
                self._runtime = AgentRuntime(deps=deps, graph=build_graph(deps, checkpointer))
        return self._runtime

    async def close(self) -> None:
        await self._stack.aclose()
