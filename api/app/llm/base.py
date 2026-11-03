"""`LLMProvider` protocol (PLAN §5 Providers): what graph nodes depend on. `ClaudeClient` is the
only real implementation; `FakeLLM` (app/llm/fake.py) scripts responses for tests and the eval
harness plumbing."""

from typing import Any, Protocol

from pydantic import BaseModel

from app.core.models_registry import NodeKey
from app.llm.claude import CompleteResult, ParseResult, ToolStartHook, TurnPrefixGuard


class LLMProvider(Protocol):
    @property
    def mode(self) -> str: ...

    async def parse[T: BaseModel](
        self,
        node: NodeKey,
        *,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        output_format: type[T],
    ) -> ParseResult[T]: ...

    async def complete(
        self,
        node: NodeKey,
        *,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        prefix_guard: TurnPrefixGuard | None = None,
        on_tool_start: ToolStartHook | None = None,
    ) -> CompleteResult: ...
