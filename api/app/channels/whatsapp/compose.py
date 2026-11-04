"""Compose agent/staff text for WhatsApp (step 6.3.4): WhatsApp markup (`*bold*`), no markdown
tables or headings, ≤ 4096 chars per message (split on paragraph/sentence boundaries), quick
replies → reply buttons (≤ 3, title ≤ 20 chars) or a list (≤ 10 rows)."""

import re
from dataclasses import dataclass, field

TEXT_LIMIT = 4096
INTERACTIVE_BODY_LIMIT = 1024
BUTTON_TITLE = 20
LIST_ROW_TITLE = 24


@dataclass
class Outgoing:
    parts: list[str]
    buttons: list[str] = field(default_factory=list)  # attached to the last part
    list_rows: list[str] = field(default_factory=list)


def _table_to_lines(block: str) -> str:
    """Markdown table → "a · b · c" lines (header separator dropped)."""
    lines = []
    for row in block.strip().splitlines():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        lines.append(" · ".join(c for c in cells if c))
    return "\n".join(lines)


def to_whatsapp_markup(text: str) -> str:
    out = re.sub(r"(?m)(^\|.*\|[ \t]*\n?)+", lambda m: _table_to_lines(m.group(0)) + "\n", text)
    out = re.sub(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", r"*\1*", out)  # headings → bold line
    out = re.sub(r"\*\*(.+?)\*\*", r"*\1*", out)  # **bold** → *bold*
    out = re.sub(r"__(.+?)__", r"_\1_", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", out)  # links → text (url)
    out = re.sub(r"(?m)^\s*[-*]\s+", "• ", out)  # bullets
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def split_text(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"))
        if cut < limit // 2:
            cut = max(window.rfind("۔ "), window.rfind(". "), window.rfind("? "))
            cut = cut + 1 if cut >= limit // 2 else limit
        parts.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return parts


def _short(label: str, n: int) -> str:
    label = " ".join(label.split())
    return label if len(label) <= n else label[: n - 1].rstrip() + "…"


def compose(text: str, quick_replies: list[str] | None = None) -> Outgoing:
    body = to_whatsapp_markup(text)
    qr = [q for q in (quick_replies or []) if q and q.strip()]
    # Interactive bodies are capped at 1024 chars → long replies go as text + a buttons tail.
    parts = split_text(body)
    if not qr:
        return Outgoing(parts=parts)
    if len(parts[-1]) > INTERACTIVE_BODY_LIMIT:
        parts = split_text(body, INTERACTIVE_BODY_LIMIT)
    if len(qr) <= 3 and all(len(q.strip()) <= BUTTON_TITLE for q in qr):
        return Outgoing(parts=parts, buttons=[q.strip() for q in qr])
    return Outgoing(parts=parts, list_rows=[_short(q, LIST_ROW_TITLE) for q in qr[:10]])
