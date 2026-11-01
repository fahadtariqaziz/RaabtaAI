"""Pinned Claude models per graph node (PLAN §7, HANDOFF D-06/D-12).

Changing a model ID, effort or max_tokens is a *release*: evals must pass (PLAN §12).
Override for experiments with env `RAABTA_MODEL_<NODE>` (e.g. RAABTA_MODEL_AGENT_SIMPLE).

Notes on current API behaviour (see CLAUDE.md):
- Thinking is adaptive and cannot be disabled on these models; depth is set via `effort`,
  which we always send explicitly (Opus 5.5 / Haiku 5.5 default to `medium`).
- `max_tokens` is a ceiling that includes thinking, not a spend target.
"""

import os
from dataclasses import dataclass, replace
from typing import Literal

OPUS = "claude-opus-5-5"
HAIKU = "claude-haiku-5-5"

Effort = Literal["low", "medium", "high", "xhigh", "max"]
NodeKey = Literal[
    "agent_simple",  # D-12 hybrid: FAQ turns (router complexity=simple)
    "agent_complex",  # bookings, fee module, multi-step, escalations
    "guard_in",
    "router",
    "answer_check",
    "tone_check",
    "summarizer",
    "facts_extractor",
    "receipt_reader",
    "eval_judge",
]


@dataclass(frozen=True)
class ModelSpec:
    model: str
    effort: Effort
    max_tokens: int


_PINNED: dict[NodeKey, ModelSpec] = {
    "agent_simple": ModelSpec(HAIKU, "low", 4_000),
    "agent_complex": ModelSpec(OPUS, "medium", 8_000),
    "guard_in": ModelSpec(HAIKU, "low", 2_000),
    "router": ModelSpec(HAIKU, "low", 2_000),
    "answer_check": ModelSpec(HAIKU, "low", 3_000),
    "tone_check": ModelSpec(HAIKU, "low", 2_000),
    "summarizer": ModelSpec(HAIKU, "low", 3_000),
    "facts_extractor": ModelSpec(OPUS, "high", 32_000),
    "receipt_reader": ModelSpec(OPUS, "medium", 4_000),
    "eval_judge": ModelSpec(OPUS, "high", 8_000),
}

NODES: tuple[NodeKey, ...] = tuple(_PINNED)


def spec_for(node: NodeKey) -> ModelSpec:
    """Model spec for a node, honouring an optional `RAABTA_MODEL_<NODE>` override."""
    spec = _PINNED[node]
    override = os.environ.get(f"RAABTA_MODEL_{node.upper()}")
    return replace(spec, model=override) if override else spec
