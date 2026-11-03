"""ClaudeClient branches with a mocked SDK (step 3.1): request shape per model family, stop_reason
handling, retries, cache breakpoints, prefix guard, cassettes, cost/llm_runs records."""

import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2 as httpx
import pytest

from app.llm.claude import (
    CassetteMissingError,
    ClaudeClient,
    LLMError,
    PrefixViolationError,
    RefusalError,
    TurnPrefixGuard,
    with_message_breakpoint,
)
from app.llm.runs import run_record, to_row

SYSTEM = [
    {"type": "text", "text": "global rules", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "tenant block", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "skills", "cache_control": {"type": "ephemeral"}},
]
MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": [{"type": "text", "text": "fee?"}]}]
TOOLS = [{"name": "get_fee_table", "description": "d", "input_schema": {"type": "object"}}]


class Block(SimpleNamespace):
    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def response(
    stop: str = "end_turn",
    blocks: list[Block] | None = None,
    *,
    iterations: list[Any] | None = None,
    category: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop,
        stop_details=SimpleNamespace(category=category) if category else None,
        model="claude-opus-5-5",
        content=blocks if blocks is not None else [Block(type="text", text="Jee, 12,500 PKR.")],
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=50,
            cache_read_input_tokens=800,
            cache_creation_input_tokens=0,
            iterations=iterations,
        ),
    )


class FakeAPI:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def client_with(responses: list[Any], **kw: Any) -> tuple[ClaudeClient, FakeAPI, FakeAPI]:
    client = ClaudeClient("k", mode="live", **kw)
    plain, beta = FakeAPI(responses), FakeAPI(responses)
    client._client = SimpleNamespace(  # type: ignore[assignment]
        messages=plain, beta=SimpleNamespace(messages=beta)
    )
    return client, plain, beta


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_s: float) -> None:
        return None

    monkeypatch.setattr("app.llm.claude.asyncio.sleep", instant)


def _err(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


async def test_opus_uses_beta_with_fallback_effort_and_tool_choice_auto() -> None:
    client, plain, beta = client_with([response()])
    result = await client.complete("agent_complex", system=SYSTEM, messages=MESSAGES, tools=TOOLS)
    assert not plain.calls
    kw = beta.calls[0]
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["fallbacks"] == "default"
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["tool_choice"] == {"type": "auto"}
    assert kw["timeout"] == 90.0
    for banned in ("temperature", "top_p", "top_k", "thinking"):
        assert banned not in kw
    assert result.text == "Jee, 12,500 PKR."
    assert result.cache_read_tokens == 800
    # 3 system breakpoints + 1 on the last user block = 4 (API maximum); input not mutated
    assert kw["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in MESSAGES[0]["content"][-1]


async def test_haiku_uses_plain_messages_without_fallback() -> None:
    client, plain, beta = client_with([response()])
    await client.complete("agent_simple", system="s", messages=MESSAGES)
    assert not beta.calls
    kw = plain.calls[0]
    assert "betas" not in kw and "fallbacks" not in kw and "tools" not in kw
    assert kw["output_config"] == {"effort": "low"}


def test_breakpoints_never_exceed_four() -> None:
    four = [*SYSTEM, {"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}]
    out = with_message_breakpoint(four, MESSAGES)
    assert "cache_control" not in out[-1]["content"][-1]
    out = with_message_breakpoint("plain", [{"role": "user", "content": "hi"}])
    assert out[0]["content"] == [
        {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}
    ]
    # breakpoint lands on the last *user* message, not an appended operator note
    msgs = [*MESSAGES, {"role": "system", "content": "operator note"}]
    out = with_message_breakpoint(SYSTEM, msgs)
    assert out[-1] == {"role": "system", "content": "operator note"}
    assert "cache_control" in out[0]["content"][-1]


async def test_refusal_raises_with_category() -> None:
    client, _, _ = client_with([response("refusal", [], category="cyber")])
    with pytest.raises(RefusalError) as exc:
        await client.complete("agent_complex", system="s", messages=MESSAGES)
    assert exc.value.category == "cyber"


async def test_max_tokens_retries_once_with_more_room() -> None:
    client, _, beta = client_with([response("max_tokens"), response()])
    await client.complete("agent_complex", system="s", messages=MESSAGES)
    assert [c["max_tokens"] for c in beta.calls] == [8000, 12000]

    client, _, _ = client_with([response("max_tokens"), response("max_tokens")])
    with pytest.raises(LLMError):
        await client.complete("agent_complex", system="s", messages=MESSAGES)


async def test_tool_use_blocks_are_preserved_for_the_loop() -> None:
    blocks = [
        Block(type="thinking", thinking="plan", signature="abc=="),
        Block(type="tool_use", id="t1", name="get_fee_table", input={"program_or_class": "3"}),
        Block(type="tool_use", id="t2", name="get_key_dates", input={"kind": None}),
    ]
    client, _, _ = client_with([response("tool_use", blocks)])
    result = await client.complete("agent_complex", system="s", messages=MESSAGES, tools=TOOLS)
    assert result.stop_reason == "tool_use"
    assert result.content[0] == {"type": "thinking", "thinking": "plan", "signature": "abc=="}
    assert [(u.id, u.name) for u in result.tool_uses] == [
        ("t1", "get_fee_table"),
        ("t2", "get_key_dates"),
    ]
    assert result.text == ""


async def test_retryable_errors_back_off_and_client_errors_raise() -> None:
    client, _, beta = client_with(
        [
            _err(anthropic.RateLimitError, 429),
            _err(anthropic.InternalServerError, 529),
            anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")),
            response(),
        ]
    )
    await client.complete("agent_complex", system="s", messages=MESSAGES)
    assert len(beta.calls) == 4

    client, _, beta = client_with([_err(anthropic.BadRequestError, 400), response()])
    with pytest.raises(anthropic.BadRequestError):
        await client.complete("agent_complex", system="s", messages=MESSAGES)
    assert len(beta.calls) == 1


async def test_fallback_flag_from_usage_iterations() -> None:
    its = [SimpleNamespace(type="message"), SimpleNamespace(type="fallback_message")]
    client, _, _ = client_with([response(iterations=its)])
    result = await client.complete("agent_complex", system="s", messages=MESSAGES)
    assert result.fallback_used


async def test_stream_reports_tool_starts() -> None:
    final = response("tool_use", [Block(type="tool_use", id="t1", name="book_visit", input={})])

    class Stream:
        async def __aenter__(self) -> "Stream":
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

        def __aiter__(self) -> Any:
            async def gen() -> Any:
                yield SimpleNamespace(type="message_start")
                yield SimpleNamespace(
                    type="content_block_start",
                    content_block=SimpleNamespace(type="tool_use", name="book_visit"),
                )

            return gen()

        async def get_final_message(self) -> Any:
            return final

    client, _, beta = client_with([])
    beta.stream = lambda **kw: Stream()  # type: ignore[attr-defined]
    seen: list[str] = []

    async def hook(name: str) -> None:
        seen.append(name)

    result = await client.stream("agent_complex", system="s", messages=MESSAGES, on_tool_start=hook)
    assert seen == ["book_visit"]
    assert result.tool_uses[0].name == "book_visit"


async def test_record_then_replay_complete(tmp_path: Path) -> None:
    client, _, _ = client_with([response()], cassette_dir=tmp_path)
    client.mode = "record"
    live = await client.complete("agent_complex", system=SYSTEM, messages=MESSAGES, tools=TOOLS)
    replay = ClaudeClient(None, mode="replay", cassette_dir=tmp_path)
    again = await replay.complete("agent_complex", system=SYSTEM, messages=MESSAGES, tools=TOOLS)
    assert again.text == live.text and again.replayed
    assert again.request_hash == live.request_hash
    assert again.cost_usd == Decimal("0")
    with pytest.raises(CassetteMissingError):
        await replay.complete("agent_complex", system=SYSTEM, messages=[*MESSAGES, *MESSAGES])


def test_prefix_guard_allows_append_only() -> None:
    guard = TurnPrefixGuard()
    msgs: list[dict[str, Any]] = list(MESSAGES)
    guard.check(TOOLS, SYSTEM, msgs)
    msgs = [*msgs, {"role": "assistant", "content": [{"type": "text", "text": "x"}]}]
    guard.check(TOOLS, SYSTEM, msgs)  # appended → fine
    # cache markers don't count as edits
    guard.check(TOOLS, SYSTEM, with_message_breakpoint(SYSTEM, msgs))
    with pytest.raises(PrefixViolationError):
        guard.check(TOOLS, SYSTEM, [{"role": "user", "content": "edited"}, *msgs[1:]])
    guard = TurnPrefixGuard()
    guard.check(TOOLS, SYSTEM, msgs)
    with pytest.raises(PrefixViolationError):
        guard.check(TOOLS, [*SYSTEM[:2]], msgs)


async def test_cost_record_and_llm_runs_row() -> None:
    client, _, _ = client_with([response(iterations=[SimpleNamespace(type="fallback_message")])])
    result = await client.complete("agent_complex", system="s", messages=MESSAGES)
    rec = run_record("agent_complex", result, prompt_hash="abc", skills=["lead-capture@1"])
    # 1000 in × $4 + 50 out × $20 + 800 cache-read × $0.20 per MTok
    assert Decimal(rec["cost_usd"]) == Decimal("0.005160")
    row = to_row(uuid.uuid4(), rec, conversation_id=uuid.uuid4())
    assert row.cache_read_tokens == 800 and row.fallback_used
    assert row.skills == ["lead-capture@1"] and row.prompt_hash == "abc"
    failed = to_row(uuid.uuid4(), run_record("router", error="timeout" * 200, model="m"))
    assert failed.error is not None and len(failed.error) == 500
