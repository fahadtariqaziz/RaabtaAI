"""Grounding helpers for `answer_check` (G2, PLAN §11): every number in a draft must appear in
the turn's sources/tool outputs (or what the contact typed / the turn context). Exact match on
the integer value after normalization (PKR 12,500 = 12500 = Rs. 12,500/- ; Urdu digits too),
plus the checker prompt input and the repair feedback format."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agent.schemas import CheckResult
from app.kb.text import estimate_tokens

URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# A number not glued to letters (so booking codes like K7M2QX and "1st" are ignored).
NUMBER = re.compile(r"(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![A-Za-z0-9])")
SMALL_OK = {Decimal(n) for n in range(4)}  # "one question", "2 options" style counts
CHECK_INPUT_BUDGET = 5000


def numbers(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for whole, frac in NUMBER.findall(text.translate(URDU_DIGITS)):
        try:
            value = Decimal(whole.replace(",", "") + (f".{frac}" if frac else ""))
        except InvalidOperation:
            continue
        found.add(value.normalize() if frac else value)
    return found


def unsupported_numbers(draft: str, corpus: list[str]) -> list[str]:
    allowed = set().union(*(numbers(t) for t in corpus)) if corpus else set()
    missing = sorted(n for n in numbers(draft) - allowed if n not in SMALL_OK)
    return [format(n, "f") for n in missing]


def checker_input(
    *,
    draft: str,
    sources: list[dict[str, Any]],
    tool_outputs: list[dict[str, Any]],
    language: str,
    module: str,
    verified: bool,
    profile: str = "",
) -> str:
    """User content for the answer_check node (≤ 5k tokens: sources trimmed last-first). The
    institution profile (tenant block) is always the first source (`id="profile"`)."""
    head = (
        f"<expected_language>{language}</expected_language>\n<module>{module}</module>\n"
        f"<verified>{'yes' if verified else 'no'}</verified>\n"
    )
    tail = f"<draft>\n{draft}\n</draft>"
    parts = [f'<source id="profile">\n{profile}\n</source>'] if profile else []
    parts += [f'<source id="{s["id"]}">\n{s["text"]}\n</source>' for s in sources]
    parts += [
        f'<tool_output name="{t["name"]}">\n{t["content"]}\n</tool_output>'
        for t in tool_outputs
        if t["name"] not in ("search_knowledge",) and not t.get("is_error")
    ]
    budget = CHECK_INPUT_BUDGET - estimate_tokens(head + tail)
    kept: list[str] = []
    for part in parts:
        if estimate_tokens("\n".join([*kept, part])) > budget:
            break
        kept.append(part)
    body = "\n".join(kept) if kept else "(no sources were retrieved this turn)"
    return f"{head}<sources>\n{body}\n</sources>\n{tail}"


def repair_note(check: CheckResult | None, numbers_missing: list[str], script_ok: bool) -> str:
    """Operator note appended (role=system) for the single repair attempt."""
    problems: list[str] = []
    if numbers_missing:
        listed = ", ".join(numbers_missing)
        problems.append(
            f"Numbers not found in any tool result: {listed}. Drop them, or use only the exact "
            "values the tools returned; never compute."
        )
    if check is not None:
        problems += [f"Unsupported: {c}" for c in check.unsupported_claims[:5]]
        problems += [f"Fix: {f}" for f in check.fixes[:5]]
        if check.identity_leak:
            problems.append("Remove all student-specific fee details: the contact is not verified.")
    if not script_ok:
        problems.append("Write the reply in the contact's language and script.")
    listing = "\n".join(f"- {p}" for p in problems) or "- Re-check every fact against the tools."
    return (
        "Review note from the grounding check — your draft reply was NOT sent:\n"
        f"{listing}\n"
        "Write the corrected reply now: keep only facts supported by this turn's tool results; "
        "if something cannot be supported, use the fallback phrase for that part. Reply with the "
        "message text only."
    )
