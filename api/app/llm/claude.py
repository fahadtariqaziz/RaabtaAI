"""Claude client wrapper (PLAN §8, CLAUDE.md "Claude API rules").

- `parse(node, …, output_format=Model)` — structured outputs for classifiers/extractors;
- `complete(node, …, tools=…)` — one model call (text + tool_use blocks) for the agent tool loop;
  `on_tool_start` switches to the streaming endpoint and reports tool-call starts as they arrive
  (widget `status` events) — the final message is read with `get_final_message()`;
- model + effort + max_tokens from `models_registry` (effort always explicit; no `thinking`,
  no sampling params, no prefill, `tool_choice` auto only, tools are `strict`);
- Opus nodes go through `client.beta.messages.*` with `server-side-fallback-2026-07-01` +
  `fallbacks="default"`; Haiku has no fallback → callers supply a safe default on refusal;
- `stop_reason` checked before reading content (`refusal` → `RefusalError` with
  `stop_details.category` logged, `max_tokens` → one retry with +50% `max_tokens`);
- SDK retries disabled; jittered backoff here on RateLimitError / 5xx+529 / connection errors;
  per-node timeouts;
- cache breakpoints: the caller marks system blocks (global, tenant, skills); `complete` adds one
  on the last user block (≤ 4 total); `TurnPrefixGuard` asserts the request prefix is append-only
  within a turn (preserved thinking);
- cassettes: `RAABTA_LLM_RECORD=1` writes `evals/cassettes/<node>/<hash>.json`,
  `RAABTA_LLM_REPLAY=1` serves them (no network, no spend; a missing cassette is an error).
"""

import asyncio
import copy
import hashlib
import json
import os
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import anthropic
import structlog
from pydantic import BaseModel

from app.core.models_registry import NodeKey, spec_for
from app.llm.cost import cost_usd

log = structlog.get_logger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
CASSETTE_DIR = Path(__file__).resolve().parents[2] / "evals" / "cassettes"
RETRIES = 3
MAX_BREAKPOINTS = 4
# Per-node request timeouts in seconds (PLAN §8).
TIMEOUTS: dict[str, float] = {
    "guard_in": 20.0,
    "router": 20.0,
    "answer_check": 30.0,
    "tone_check": 20.0,
    "summarizer": 30.0,
    "agent_simple": 60.0,
    "agent_complex": 90.0,
    "facts_extractor": 300.0,
    "receipt_reader": 90.0,
    "eval_judge": 120.0,
}
CACHE = {"type": "ephemeral"}
Mode = Literal["live", "record", "replay"]
ToolStartHook = Callable[[str], Awaitable[None]]


class LLMError(RuntimeError):
    pass


class RefusalError(LLMError):
    def __init__(self, category: str | None) -> None:
        super().__init__(f"model refused (category={category})")
        self.category = category


class CassetteMissingError(LLMError):
    pass


class PrefixViolationError(LLMError):
    """A request within one turn rewrote (instead of appended to) the previous request."""


@dataclass(kw_only=True)
class LLMResult:
    model: str
    effort: str
    stop_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    fallback_used: bool = False
    replayed: bool = False
    request_hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def cost_usd(self) -> Decimal:
        if self.replayed:
            return Decimal("0")
        return cost_usd(
            self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read=self.cache_read_tokens,
            cache_write=self.cache_write_tokens,
        )

    def usage_record(self) -> dict[str, Any]:
        """Token/cost fields for an `llm_runs` row (JSON-safe; see app/llm/runs.py)."""
        return {
            "model": self.model,
            "effort": self.effort,
            "stop_reason": self.stop_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cost_usd": str(self.cost_usd),
            "latency_ms": self.latency_ms,
            "fallback_used": self.fallback_used,
        }


@dataclass(kw_only=True)
class ParseResult[T: BaseModel](LLMResult):
    output: T


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(kw_only=True)
class CompleteResult(LLMResult):
    content: list[dict[str, Any]]  # assistant blocks as sent back (thinking blocks untouched)

    @property
    def text(self) -> str:
        return "\n\n".join(
            b["text"].strip() for b in self.content if b.get("type") == "text" and b.get("text")
        ).strip()

    @property
    def tool_uses(self) -> list[ToolUse]:
        return [
            ToolUse(id=b["id"], name=b["name"], input=dict(b.get("input") or {}))
            for b in self.content
            if b.get("type") == "tool_use"
        ]


def env_mode() -> Mode:
    if os.environ.get("RAABTA_LLM_REPLAY") == "1":
        return "replay"
    if os.environ.get("RAABTA_LLM_RECORD") == "1":
        return "record"
    return "live"


def request_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def strip_cache_control(value: Any) -> Any:
    """Deep copy without `cache_control` keys (markers don't change what a prefix *is*)."""
    if isinstance(value, dict):
        return {k: strip_cache_control(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [strip_cache_control(v) for v in value]
    return value


class TurnPrefixGuard:
    """Debug assert for preserved thinking (PLAN §8): within one turn, tools and system must be
    identical and the message list may only grow at the end."""

    def __init__(self) -> None:
        self._prev: tuple[str, str, list[str]] | None = None

    def check(
        self,
        tools: list[dict[str, Any]] | None,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> None:
        cur = (
            request_hash(strip_cache_control(tools or [])),
            request_hash(strip_cache_control(system)),
            [request_hash(strip_cache_control(m)) for m in messages],
        )
        if self._prev is not None:
            p_tools, p_system, p_msgs = self._prev
            if cur[0] != p_tools or cur[1] != p_system:
                raise PrefixViolationError("tools/system changed within a turn")
            if cur[2][: len(p_msgs)] != p_msgs:
                raise PrefixViolationError("earlier messages were edited within a turn")
        self._prev = cur

    @property
    def prefix_hash(self) -> str | None:
        return request_hash(self._prev) if self._prev else None


def with_message_breakpoint(
    system: str | list[dict[str, Any]], messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Copy of `messages` with a cache breakpoint on the last user content block, if the system
    blocks leave room (max 4 breakpoints per request)."""
    used = (
        sum(1 for b in system if isinstance(b, dict) and "cache_control" in b)
        if isinstance(system, list)
        else 0
    )
    out = copy.deepcopy(messages)
    if used >= MAX_BREAKPOINTS:
        return out
    for msg in reversed(out):
        if msg.get("role") != "user":
            continue
        content = msg["content"]
        if isinstance(content, str):
            msg["content"] = [{"type": "text", "text": content, "cache_control": CACHE}]
        elif content:
            content[-1] = {**content[-1], "cache_control": CACHE}
        break
    return out


def _block_dict(block: Any) -> dict[str, Any]:
    data: dict[str, Any] = block.model_dump(mode="json", by_alias=True, exclude_none=True)
    data.pop("parsed_output", None)
    return data


def _usage_fields(response: Any) -> dict[str, Any]:
    usage = response.usage
    iterations = getattr(usage, "iterations", None) or []
    return {
        "input_tokens": usage.input_tokens or 0,
        "output_tokens": usage.output_tokens or 0,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
        "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
        "fallback_used": any(getattr(it, "type", "") == "fallback_message" for it in iterations),
    }


def _refusal(node: str, response: Any) -> RefusalError:
    details = getattr(response, "stop_details", None)
    category = getattr(details, "category", None)
    log.warning("llm.refusal", node=node, category=category, model=str(response.model))
    return RefusalError(category)


class ClaudeClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        mode: Mode | None = None,
        cassette_dir: Path = CASSETTE_DIR,
    ) -> None:
        self.mode = mode or env_mode()
        self.cassette_dir = cassette_dir
        self._client = (
            anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
            if self.mode != "replay"
            else None
        )

    def _cassette(self, node: str, digest: str) -> Path:
        return self.cassette_dir / node / f"{digest}.json"

    def _load_cassette(self, node: str, digest: str) -> dict[str, Any]:
        path = self._cassette(node, digest)
        if not path.is_file():
            raise CassetteMissingError(f"no cassette for {node} ({digest}) at {path}")
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def _save_cassette(self, node: str, digest: str, record: dict[str, Any]) -> None:
        path = self._cassette(node, digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- structured outputs -------------------------------------------------------------

    async def parse[T: BaseModel](
        self,
        node: NodeKey,
        *,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        output_format: type[T],
    ) -> ParseResult[T]:
        spec = spec_for(node)
        digest = request_hash(
            {
                "model": spec.model,
                "effort": spec.effort,
                "system": system,
                "messages": messages,
                "schema": output_format.model_json_schema(),
            }
        )
        if self.mode == "replay":
            data = self._load_cassette(node, digest)
            return ParseResult(
                output=output_format.model_validate(data["output"]),
                model=data["model"],
                effort=spec.effort,
                stop_reason=data["stop_reason"],
                input_tokens=data.get("input_tokens", 0),
                output_tokens=data.get("output_tokens", 0),
                replayed=True,
                request_hash=digest,
            )
        result = await self._live(node, system, messages, output_format)
        result.request_hash = digest
        if self.mode == "record":
            self._save_cassette(
                node,
                digest,
                {
                    "node": node,
                    "model": result.model,
                    "stop_reason": result.stop_reason,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "output": result.output.model_dump(mode="json"),
                },
            )
        return result

    async def _live[T: BaseModel](
        self,
        node: NodeKey,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        output_format: type[T],
    ) -> ParseResult[T]:
        assert self._client is not None  # noqa: S101
        client = self._client
        spec = spec_for(node)
        max_tokens = spec.max_tokens
        timeout = TIMEOUTS.get(node, 60.0)
        is_opus = spec.model.startswith("claude-opus")
        for size_attempt in range(2):
            started = time.monotonic()
            response = await self._with_backoff(
                node,
                lambda mt=max_tokens: (
                    client.beta.messages.parse(
                        model=spec.model,
                        max_tokens=mt,
                        system=system,  # type: ignore[arg-type]
                        messages=messages,  # type: ignore[arg-type]
                        output_format=output_format,
                        output_config={"effort": spec.effort},
                        betas=[FALLBACK_BETA],
                        fallbacks="default",
                        timeout=timeout,
                    )
                    if is_opus
                    else client.messages.parse(
                        model=spec.model,
                        max_tokens=mt,
                        system=system,  # type: ignore[arg-type]
                        messages=messages,  # type: ignore[arg-type]
                        output_format=output_format,
                        output_config={"effort": spec.effort},
                        timeout=timeout,
                    )
                ),
            )
            latency = int((time.monotonic() - started) * 1000)
            stop = str(response.stop_reason)
            if stop == "refusal":
                raise _refusal(node, response)
            if stop == "max_tokens" and size_attempt == 0:
                max_tokens = int(max_tokens * 1.5)
                continue
            parsed = response.parsed_output
            if parsed is None:
                raise LLMError(f"{node}: no parsed output (stop_reason={stop})")
            return ParseResult(
                output=parsed,
                model=response.model,
                effort=spec.effort,
                stop_reason=stop,
                latency_ms=latency,
                **_usage_fields(response),
            )
        raise LLMError(f"{node}: output exceeded max_tokens twice")

    # ---- free-form / tool calls ---------------------------------------------------------

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
        """One model call. Callers loop on `stop_reason == "tool_use"` (append-only)."""
        if prefix_guard is not None:
            prefix_guard.check(tools, system, messages)
        spec = spec_for(node)
        digest = request_hash(
            {
                "model": spec.model,
                "effort": spec.effort,
                "system": strip_cache_control(system),
                "messages": strip_cache_control(messages),
                "tools": strip_cache_control(tools or []),
            }
        )
        if self.mode == "replay":
            data = self._load_cassette(node, digest)
            result = CompleteResult(
                content=data["content"],
                model=data["model"],
                effort=spec.effort,
                stop_reason=data["stop_reason"],
                input_tokens=data.get("input_tokens", 0),
                output_tokens=data.get("output_tokens", 0),
                replayed=True,
                request_hash=digest,
            )
            if on_tool_start is not None:
                for use in result.tool_uses:
                    await on_tool_start(use.name)
            return result
        result = await self._complete_live(
            node, system, messages, tools, max_tokens or spec.max_tokens, on_tool_start
        )
        result.request_hash = digest
        if self.mode == "record":
            self._save_cassette(
                node,
                digest,
                {
                    "node": node,
                    "model": result.model,
                    "stop_reason": result.stop_reason,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "content": result.content,
                },
            )
        return result

    async def stream(
        self,
        node: NodeKey,
        *,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_tool_start: ToolStartHook | None = None,
        prefix_guard: TurnPrefixGuard | None = None,
    ) -> CompleteResult:
        """Streaming variant of `complete` (long outputs; tool-start status events). Text is
        never forwarded to users from here — replies go out only after `answer_check` (D-11)."""

        async def _noop(_name: str) -> None:
            return None

        return await self.complete(
            node,
            system=system,
            messages=messages,
            tools=tools,
            prefix_guard=prefix_guard,
            on_tool_start=on_tool_start or _noop,
        )

    def _request_kwargs(
        self,
        node: NodeKey,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        spec = spec_for(node)
        kwargs: dict[str, Any] = {
            "model": spec.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": with_message_breakpoint(system, messages),
            "output_config": {"effort": spec.effort},
            "timeout": TIMEOUTS.get(node, 60.0),
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = {"type": "auto"}
        if spec.model.startswith("claude-opus"):
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    async def _send(self, kwargs: dict[str, Any], on_tool_start: ToolStartHook | None) -> Any:
        assert self._client is not None  # noqa: S101
        api: Any = self._client.beta.messages if "betas" in kwargs else self._client.messages
        if on_tool_start is None:
            return await api.create(**kwargs)
        async with api.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_start" and event.content_block.type == "tool_use":
                    await on_tool_start(event.content_block.name)
            return await stream.get_final_message()

    async def _complete_live(
        self,
        node: NodeKey,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        on_tool_start: ToolStartHook | None,
    ) -> CompleteResult:
        spec = spec_for(node)
        for size_attempt in range(2):
            kwargs = self._request_kwargs(node, system, messages, tools, max_tokens)
            started = time.monotonic()
            response = await self._with_backoff(
                node, lambda kw=kwargs: self._send(kw, on_tool_start)
            )
            latency = int((time.monotonic() - started) * 1000)
            stop = str(response.stop_reason)
            if stop == "refusal":
                raise _refusal(node, response)
            if stop == "max_tokens" and size_attempt == 0:
                max_tokens = int(max_tokens * 1.5)
                continue
            if stop == "max_tokens":
                raise LLMError(f"{node}: output exceeded max_tokens twice")
            return CompleteResult(
                content=[_block_dict(b) for b in response.content],
                model=str(response.model),
                effort=spec.effort,
                stop_reason=stop,
                latency_ms=latency,
                **_usage_fields(response),
            )
        raise LLMError("unreachable")

    async def _with_backoff(self, node: str, call: Any) -> Any:
        for attempt in range(RETRIES + 1):
            try:
                return await call()
            except anthropic.RateLimitError:
                if attempt == RETRIES:
                    raise
            except anthropic.APIStatusError as exc:
                if exc.status_code < 500 or attempt == RETRIES:
                    raise
            except anthropic.APIConnectionError:
                if attempt == RETRIES:
                    raise
            delay = min(2**attempt + random.random(), 30)  # noqa: S311
            log.info("llm.retry", node=node, attempt=attempt + 1, delay=round(delay, 2))
            await asyncio.sleep(delay)
        raise LLMError("unreachable")
