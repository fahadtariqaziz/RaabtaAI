"""`llm_runs` rows (PLAN §8 cost logging): one per model call, with tokens incl. cache, cost,
latency, stop_reason, fallback flag, prompt hash and skill versions."""

import uuid
from decimal import Decimal
from typing import Any

from app.llm.claude import LLMResult
from app.models.conversations import LlmRun


def run_record(
    node: str,
    result: LLMResult | None = None,
    *,
    prompt_hash: str | None = None,
    skills: list[str] | None = None,
    error: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """JSON-safe record (kept in graph state until the turn is persisted)."""
    base: dict[str, Any] = result.usage_record() if result else {"model": model or "unknown"}
    return {
        **base,
        "node": node,
        "prompt_hash": prompt_hash,
        "skills": list(skills or []),
        "error": error[:500] if error else None,
    }


def to_row(
    institution_id: uuid.UUID, record: dict[str, Any], conversation_id: uuid.UUID | None = None
) -> LlmRun:
    return LlmRun(
        institution_id=institution_id,
        conversation_id=conversation_id,
        node=record["node"],
        model=record.get("model") or "unknown",
        prompt_hash=record.get("prompt_hash"),
        skills=record.get("skills") or [],
        effort=record.get("effort"),
        input_tokens=record.get("input_tokens", 0),
        cache_read_tokens=record.get("cache_read_tokens", 0),
        cache_write_tokens=record.get("cache_write_tokens", 0),
        output_tokens=record.get("output_tokens", 0),
        cost_usd=Decimal(record.get("cost_usd") or "0"),
        latency_ms=record.get("latency_ms"),
        stop_reason=record.get("stop_reason"),
        fallback_used=bool(record.get("fallback_used")),
        error=record.get("error"),
    )
