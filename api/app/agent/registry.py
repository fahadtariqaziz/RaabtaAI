"""Tool registry (PLAN §5 DO, §9.3).

- Pydantic `Input`/`Output` per tool → strict JSON schema (`additionalProperties: false`, every
  property required; optional = nullable), `strict: True` definitions;
- `permission` (`public` | `verified_parent` | `staff`), `side_effect`, `modules`;
- `definitions(module)` is name-sorted (cache-stable tools prefix);
- `execute()` validates input with Pydantic (never string matching), checks permission, runs the
  tool in its own tenant-scoped transaction (`SET LOCAL app.institution_id` via
  `tenant_session`) with a `ToolContext` built by the graph — never an institution id from the
  model — and wraps any failure as an `is_error` tool_result with a short model-facing message;
- `manifest()` = MCP-style JSON for `GET /internal/tools`.
"""

import asyncio
import datetime as dt
import hashlib
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from anthropic import transform_schema
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tenancy import tenant_session
from app.kb.embeddings import EmbeddingProvider
from app.kb.text import estimate_tokens

log = structlog.get_logger(__name__)

Permission = Literal["public", "verified_parent", "staff"]
SideEffect = Literal["read", "write", "gate", "state"]
TOOL_RESULT_TOKENS = 2500  # PLAN §7: tool results ≤ 2.5k tokens in the agent context


class ToolError(Exception):
    """Expected failure; the message is shown to the model (not the contact)."""


@dataclass(frozen=True)
class Source:
    """Something the reply may cite: a KB chunk or an approved fact row."""

    id: str
    kind: Literal["chunk", "fact"]
    text: str
    citation: dict[str, Any] | None  # app.kb.citations.Citation as JSON

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "text": self.text, "citation": self.citation}


def source_id(prefix: str, *parts: object) -> str:
    """Deterministic short id (stable across re-ingests → replayable cassettes)."""
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode(), usedforsecurity=False)
    return f"{prefix}-{digest.hexdigest()[:6]}"


@dataclass
class ToolContext:
    """Built by the graph from DB rows loaded under RLS. Tools never see ids from the model."""

    institution_id: uuid.UUID
    contact_id: uuid.UUID
    conversation_id: uuid.UUID
    channel: str
    verified: bool
    institution_type: str
    timezone: str
    now: dt.datetime  # aware; per-turn clock (frozen in evals/tests)
    sources: list[Source] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)  # lead_saved, booked, handoff…

    def add_sources(self, items: Iterable[Source]) -> None:
        seen = {s.id for s in self.sources}
        for s in items:
            if s.id not in seen:
                self.sources.append(s)
                seen.add(s.id)


@dataclass(frozen=True)
class ToolRuntime:
    sessionmaker: async_sessionmaker[AsyncSession]
    embedder: EmbeddingProvider | None = None


ToolFn = Callable[[Any, ToolContext, AsyncSession, ToolRuntime], Awaitable[BaseModel]]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Strict tool input schema: SDK transform (unsupported constraints → description) + every
    object property required + `additionalProperties: false`, recursively."""
    schema = transform_schema(model)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            node.pop("title", None)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return schema


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    fn: ToolFn
    permission: Permission = "public"
    side_effect: SideEffect = "read"
    modules: frozenset[str] = frozenset({"admissions"})

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": strict_schema(self.input_model),
            "strict": True,
        }


@dataclass
class ToolOutcome:
    tool_use_id: str
    name: str
    content: str
    is_error: bool = False
    data: dict[str, Any] | None = None

    def block(self) -> dict[str, Any]:
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.content,
        }
        if self.is_error:
            block["is_error"] = True
        return block

    def trace(self, args: dict[str, Any]) -> dict[str, Any]:
        """Compact record for `messages.tool_calls` / history collapsing."""
        return {"name": self.name, "input": args, "is_error": self.is_error}


def _truncate(text: str, budget: int = TOOL_RESULT_TOKENS) -> str:
    if estimate_tokens(text) <= budget:
        return text
    ratio = budget / max(estimate_tokens(text), 1)
    return text[: int(len(text) * ratio)] + "\n…[truncated]"


def render_output(output: BaseModel) -> str:
    render = getattr(output, "render", None)
    text = render() if callable(render) else output.model_dump_json()
    return _truncate(str(text))


def module_tools(module: str) -> str:
    """Persona tool subset: `general` turns use the admissions toolset."""
    return "fees" if module == "fees" else "admissions"


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self, module: str) -> list[Tool]:
        subset = module_tools(module)
        return sorted(
            (t for t in self._tools.values() if subset in t.modules or "all" in t.modules),
            key=lambda t: t.name,
        )

    def definitions(self, module: str) -> list[dict[str, Any]]:
        return [t.definition() for t in self.list_tools(module)]

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "2025-06-18",
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": strict_schema(t.input_model),
                    "outputSchema": t.output_model.model_json_schema(),
                    "annotations": {
                        "permission": t.permission,
                        "sideEffect": t.side_effect,
                        "modules": sorted(t.modules),
                        "readOnlyHint": t.side_effect == "read",
                    },
                }
                for t in sorted(self._tools.values(), key=lambda t: t.name)
            ],
        }

    async def execute(
        self,
        name: str,
        raw_input: dict[str, Any],
        ctx: ToolContext,
        runtime: ToolRuntime,
        *,
        tool_use_id: str = "",
        module: str | None = None,
    ) -> ToolOutcome:
        tool = self._tools.get(name)
        if tool is None or (module is not None and tool not in self.list_tools(module)):
            return ToolOutcome(tool_use_id, name, f"Unknown tool {name!r}.", is_error=True)
        if tool.permission == "staff":
            return ToolOutcome(tool_use_id, name, "This action is staff-only.", is_error=True)
        if tool.permission == "verified_parent" and not ctx.verified:
            return ToolOutcome(
                tool_use_id,
                name,
                "Identity not verified. Ask for the student's name and class or roll number and "
                "call verify_parent first. Do not share any account details before that.",
                is_error=True,
            )
        try:
            args = tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}"
                for e in exc.errors()[:3]
            )
            return ToolOutcome(tool_use_id, name, f"Invalid input — {problems}", is_error=True)
        try:
            async with tenant_session(runtime.sessionmaker, ctx.institution_id) as session:
                output = await tool.fn(args, ctx, session, runtime)
        except ToolError as exc:
            return ToolOutcome(tool_use_id, name, str(exc), is_error=True)
        except Exception:
            log.exception("tool.failed", tool=name)
            return ToolOutcome(
                tool_use_id,
                name,
                "The lookup failed due to a temporary problem. Apologise briefly and offer to "
                "have the office follow up.",
                is_error=True,
            )
        return ToolOutcome(
            tool_use_id, name, render_output(output), data=output.model_dump(mode="json")
        )

    async def execute_all(
        self,
        uses: list[tuple[str, str, dict[str, Any]]],
        ctx: ToolContext,
        runtime: ToolRuntime,
        *,
        module: str | None = None,
    ) -> list[ToolOutcome]:
        """Parallel tool_use blocks → outcomes in the same order (one user message later)."""
        return list(
            await asyncio.gather(
                *(
                    self.execute(name, args, ctx, runtime, tool_use_id=use_id, module=module)
                    for use_id, name, args in uses
                )
            )
        )
