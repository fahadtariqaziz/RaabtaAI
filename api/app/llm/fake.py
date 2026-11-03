"""Scripted LLM for tests and offline harness runs — never used in production paths.

`FakeLLM({"router": RouteDecision(...), "agent_simple": [tool_call(...), text_reply("...")]})`:
a value is returned for every call, a list is consumed in order (last item repeats), a callable
gets the request dict and returns a value, an exception instance is raised."""

import itertools
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.core.models_registry import NodeKey, spec_for
from app.llm.claude import CompleteResult, ParseResult, ToolStartHook, TurnPrefixGuard

Responder = Any  # BaseModel | CompleteResult | list[...] | Callable[[dict], ...] | Exception
_ids = itertools.count(1)


def text_reply(text: str) -> CompleteResult:
    return CompleteResult(
        content=[{"type": "text", "text": text}],
        model="fake",
        effort="low",
        stop_reason="end_turn",
        input_tokens=100,
        output_tokens=20,
    )


def tool_call(name: str, args: dict[str, Any], *more: tuple[str, dict[str, Any]]) -> CompleteResult:
    """One assistant message with one or more (parallel) tool_use blocks."""
    blocks: list[dict[str, Any]] = [{"type": "thinking", "thinking": "…", "signature": "sig"}]
    for n, a in ((name, args), *more):
        blocks.append({"type": "tool_use", "id": f"toolu_{next(_ids):04d}", "name": n, "input": a})
    return CompleteResult(
        content=blocks,
        model="fake",
        effort="low",
        stop_reason="tool_use",
        input_tokens=100,
        output_tokens=20,
    )


class FakeLLM:
    mode = "fake"

    def __init__(self, script: dict[str, Responder] | None = None) -> None:
        self.script: dict[str, Responder] = dict(script or {})
        self.calls: list[dict[str, Any]] = []
        self._pos: dict[str, int] = {}

    def _next(self, node: str, request: dict[str, Any]) -> Any:
        if node not in self.script:
            raise AssertionError(f"FakeLLM: no script for node {node!r}")
        item = self.script[node]
        if isinstance(item, list):
            i = self._pos.get(node, 0)
            self._pos[node] = i + 1
            item = item[min(i, len(item) - 1)]
        if callable(item) and not isinstance(item, BaseModel | CompleteResult):
            fn: Callable[[dict[str, Any]], Any] = item
            item = fn(request)
        if isinstance(item, BaseException):
            raise item
        return item

    def nodes_called(self) -> list[str]:
        return [c["node"] for c in self.calls]

    async def parse[T: BaseModel](
        self,
        node: NodeKey,
        *,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        output_format: type[T],
    ) -> ParseResult[T]:
        request = {"node": node, "system": system, "messages": messages}
        self.calls.append(request)
        value = self._next(node, request)
        output = value if isinstance(value, output_format) else output_format.model_validate(value)
        spec = spec_for(node)
        return ParseResult(
            output=output,
            model=spec.model,
            effort=spec.effort,
            stop_reason="end_turn",
            input_tokens=50,
            output_tokens=10,
        )

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
    ) -> CompleteResult:
        if prefix_guard is not None:
            prefix_guard.check(tools, system, messages)
        request = {"node": node, "system": system, "messages": list(messages), "tools": tools}
        self.calls.append(request)
        value = self._next(node, request)
        result = text_reply(value) if isinstance(value, str) else value
        if not isinstance(result, CompleteResult):
            raise AssertionError(f"FakeLLM: {node} needs a CompleteResult, got {type(value)}")
        spec = spec_for(node)
        out = CompleteResult(
            content=[dict(b) for b in result.content],
            model=spec.model,
            effort=spec.effort,
            stop_reason=result.stop_reason,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        if on_tool_start is not None:
            for use in out.tool_uses:
                await on_tool_start(use.name)
        return out
