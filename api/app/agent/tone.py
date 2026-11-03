"""Tone check for LLM-generated fee text (G5, PLAN §6.2). Used by outbound personalization
(Phase 6/7) and the tone eval. Haiku refusal/error → fail-safe (use the template instead)."""

from typing import Any

from app.agent.graph import cached_system, failed_run, soft_error
from app.agent.schemas import ToneVerdict
from app.llm.base import LLMProvider
from app.llm.runs import run_record
from app.prompts import load_prompt


def tone_user_content(text: str, context: str = "") -> str:
    ctx = f"<context>\n{context}\n</context>\n" if context else ""
    return f"{ctx}<message>\n{text}\n</message>"


async def check_tone(
    llm: LLMProvider, text: str, context: str = ""
) -> tuple[ToneVerdict, dict[str, Any]]:
    prompt = load_prompt("tone_check")
    try:
        res = await llm.parse(
            "tone_check",
            system=cached_system("tone_check"),
            messages=[{"role": "user", "content": tone_user_content(text, context)}],
            output_format=ToneVerdict,
        )
    except Exception as exc:
        if not soft_error(exc):
            raise
        return ToneVerdict.fail_safe(), failed_run("tone_check", exc, prompt.hash)
    verdict = res.output
    verdict.ok = verdict.ok and verdict.score >= 4
    return verdict, run_record("tone_check", res, prompt_hash=prompt.hash)
