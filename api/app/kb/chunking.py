"""Heading-aware chunker (step 2.3).

- Units: paragraphs (split into sentences only when one paragraph alone exceeds `max_tokens`) and
  table rows (never split; each row is self-describing `Header: value | …`).
- Chunks are filled to `min_tokens`..`max_tokens`. Small sections are merged with the following
  ones (heading lines stay inline so their words are searchable); a chunk is only closed at a
  section boundary once it has reached `min_tokens`, or at the document end. A table is never
  merged with the section after it (keeps sheets/tables and their page refs separate).
- When a long section is split, the next chunk starts with the trailing ≈`overlap` share of the
  previous chunk's units (same section only).
- Each chunk keeps the page of its first unit and the heading path(s) it covers.
"""

import re
from dataclasses import dataclass, field

from app.kb.parsers.base import Block
from app.kb.text import detect_lang, estimate_tokens, looks_like_injection, normalize

MIN_TOKENS = 400
MAX_TOKENS = 800
OVERLAP = 0.15

_SENTENCE = re.compile(r"(?<=[.!?۔])\s+")


@dataclass
class ChunkDraft:
    ordinal: int
    page: int | None
    heading: str | None
    text: str
    text_norm: str
    lang: str
    tokens: int
    suspicious: bool


@dataclass
class _Unit:
    section: int
    heading_path: str
    page: int
    text: str
    tokens: int
    is_heading: bool = False
    is_row: bool = False


@dataclass
class _Open:
    units: list[_Unit] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(u.tokens for u in self.units)

    @property
    def content(self) -> list[_Unit]:
        return [u for u in self.units if not u.is_heading]


def _path(stack: list[tuple[int, str]]) -> str:
    """Heading path without the document title (level 0) once deeper headings exist."""
    parts = [h for lvl, h in stack if lvl > 0] or [h for _, h in stack]
    return " › ".join(parts)


def _units(blocks: list[Block], max_tokens: int) -> list[_Unit]:
    stack: list[tuple[int, str]] = []
    section = 0
    out: list[_Unit] = []
    for b in blocks:
        text = b.text.strip()
        if not text:
            continue
        if b.kind == "heading":
            stack = [(lvl, h) for lvl, h in stack if lvl < b.level] + [(b.level, text)]
            section += 1
            path = _path(stack)
            out.append(_Unit(section, path, b.page, text, estimate_tokens(text), is_heading=True))
            continue
        path = _path(stack)
        tokens = estimate_tokens(text)
        if b.kind == "para" and tokens > max_tokens:
            for sentence in _SENTENCE.split(text):
                if sentence.strip():
                    out.append(
                        _Unit(section, path, b.page, sentence.strip(), estimate_tokens(sentence))
                    )
        else:
            out.append(_Unit(section, path, b.page, text, tokens, is_row=b.kind == "row"))
    return out


def _tail_sentences(unit: _Unit, budget: int) -> _Unit | None:
    """Trailing sentences of a long paragraph that fit `budget` (overlap at sentence level)."""
    picked: list[str] = []
    used = 0
    for sentence in reversed([s for s in _SENTENCE.split(unit.text) if s.strip()]):
        t = estimate_tokens(sentence)
        if used + t > budget:
            break
        picked.insert(0, sentence.strip())
        used += t
    if not picked or len(picked) == len(_SENTENCE.split(unit.text)):
        return None
    text = " ".join(picked)
    return _Unit(unit.section, unit.heading_path, unit.page, text, estimate_tokens(text))


def _draft(ordinal: int, chunk: _Open) -> ChunkDraft:
    content = chunk.content or chunk.units
    headings: list[str] = []
    for u in chunk.units:
        if u.heading_path and u.heading_path not in headings:
            headings.append(u.heading_path)
    text = "\n".join(u.text for u in chunk.units)
    return ChunkDraft(
        ordinal=ordinal,
        page=content[0].page,
        heading=(" / ".join(headings[:3]) or None),
        text=text,
        text_norm=normalize(text),
        lang=detect_lang(text),
        tokens=estimate_tokens(text),
        suspicious=looks_like_injection(text),
    )


def chunk_blocks(
    blocks: list[Block],
    *,
    min_tokens: int = MIN_TOKENS,
    max_tokens: int = MAX_TOKENS,
    overlap: float = OVERLAP,
) -> list[ChunkDraft]:
    units = _units(blocks, max_tokens)
    drafts: list[ChunkDraft] = []
    current = _Open()

    def close() -> None:
        if current.content:
            drafts.append(_draft(len(drafts), current))
        current.units = []

    for unit in units:
        last = current.units[-1] if current.units else None
        new_section = last is not None and unit.section != last.section
        after_table = bool(current.content) and current.content[-1].is_row
        if new_section and (current.tokens >= min_tokens or after_table):
            close()  # tables are never merged with what follows them
        elif current.units and current.tokens + unit.tokens > max_tokens:
            same_section = last is not None and unit.section == last.section
            carry: list[_Unit] = []
            if same_section and not unit.is_heading:
                budget = int(current.tokens * overlap)
                for prev in reversed(current.content):
                    if prev.section != unit.section:
                        break
                    if prev.tokens > budget:
                        if not carry and not prev.is_row:
                            tail = _tail_sentences(prev, budget)
                            if tail is not None:
                                carry.append(tail)
                        break
                    carry.insert(0, prev)
                    budget -= prev.tokens
            close()
            current.units = carry
        current.units.append(unit)
    close()
    return drafts
