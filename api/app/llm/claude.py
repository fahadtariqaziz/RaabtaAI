"""Claude client wrapper — structured-output (`parse`) path (PLAN §8). Step 3.1 extends this
module with `complete`/`stream`/tool loops; the rules here already follow CLAUDE.md:

- model + effort + max_tokens from `models_registry` (effort always explicit; no `thinking`,
  no sampling params, no prefill);
- Opus nodes go through `client.beta.messages.*` with `server-side-fallback-2026-07-01` +
  `fallbacks="default"`; Haiku has no fallback → caller supplies a safe default on refusal;
- `stop_reason` checked before reading content (`refusal` → `RefusalError`, `max_tokens` → one
  retry with +50% `max_tokens`);
- SDK retries disabled; jittered backoff here on RateLimitError / 5xx / connection errors;
- cassettes: `RAABTA_LLM_RECORD=1` writes `evals/cassettes/<node>/<hash>.json`,
  `RAABTA_LLM_REPLAY=1` serves them (no network, no spend; a missing cassette is an error).
"""

import asyncio
import hashlib
import json
import os
import random
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import anthropic
from pydantic import BaseModel

from app.core.models_registry import NodeKey, spec_for
from app.llm.cost import cost_usd

FALLBACK_BETA = "server-side-fallback-2026-07-01"
CASSETTE_DIR = Path(__file__).resolve().parents[2] / "evals" / "cassettes"
RETRIES = 3
TIMEOUTS: dict[str, float] = {"facts_extractor": 300.0, "receipt_reader": 90.0}
Mode = Literal["live", "record", "replay"]


class LLMError(RuntimeError):
    pass


class RefusalError(LLMError):
    def __init__(self, category: str | None) -> None:
        super().__init__(f"model refused (category={category})")
        self.category = category


class CassetteMissingError(LLMError):
    pass


@dataclass
class ParseResult[T: BaseModel]:
    output: T
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
        return cost_usd(
            self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read=self.cache_read_tokens,
            cache_write=self.cache_write_tokens,
        )


def env_mode() -> Mode:
    if os.environ.get("RAABTA_LLM_REPLAY") == "1":
        return "replay"
    if os.environ.get("RAABTA_LLM_RECORD") == "1":
        return "record"
    return "live"


def request_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


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
        path = self._cassette(node, digest)
        if self.mode == "replay":
            if not path.is_file():
                raise CassetteMissingError(f"no cassette for {node} ({digest}) at {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
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
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "node": node,
                "model": result.model,
                "stop_reason": result.stop_reason,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "output": result.output.model_dump(mode="json"),
            }
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return result

    async def _live[T: BaseModel](
        self,
        node: NodeKey,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        output_format: type[T],
    ) -> ParseResult[T]:
        assert self._client is not None  # noqa: S101
        spec = spec_for(node)
        max_tokens = spec.max_tokens
        timeout = TIMEOUTS.get(node, 60.0)
        is_opus = spec.model.startswith("claude-opus")
        for size_attempt in range(2):
            started = time.monotonic()
            response = await self._with_backoff(
                lambda mt=max_tokens: (
                    self._client.beta.messages.parse(
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
                    else self._client.messages.parse(
                        model=spec.model,
                        max_tokens=mt,
                        system=system,  # type: ignore[arg-type]
                        messages=messages,  # type: ignore[arg-type]
                        output_format=output_format,
                        output_config={"effort": spec.effort},
                        timeout=timeout,
                    )
                )
            )
            latency = int((time.monotonic() - started) * 1000)
            stop = str(response.stop_reason)
            if stop == "refusal":
                details = getattr(response, "stop_details", None)
                raise RefusalError(getattr(details, "category", None))
            if stop == "max_tokens" and size_attempt == 0:
                max_tokens = int(max_tokens * 1.5)
                continue
            parsed = response.parsed_output
            if parsed is None:
                raise LLMError(f"{node}: no parsed output (stop_reason={stop})")
            usage = response.usage
            iterations = getattr(usage, "iterations", None) or []
            return ParseResult(
                output=parsed,
                model=response.model,
                effort=spec.effort,
                stop_reason=stop,
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=usage.cache_read_input_tokens or 0,
                cache_write_tokens=usage.cache_creation_input_tokens or 0,
                latency_ms=latency,
                fallback_used=any(
                    getattr(it, "type", "") == "fallback_message" for it in iterations
                ),
            )
        raise LLMError(f"{node}: output exceeded max_tokens twice")

    async def _with_backoff(self, call: Any) -> Any:
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
            await asyncio.sleep(min(2**attempt + random.random(), 30))  # noqa: S311
        raise LLMError("unreachable")
