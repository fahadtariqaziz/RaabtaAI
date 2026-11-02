"""Parser output types + the Urdu extraction-quality heuristic (step 2.2.4)."""

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BlockKind = Literal["heading", "para", "row"]


class ParseError(ValueError):
    pass


@dataclass
class Block:
    page: int  # 1-based (sheet number for spreadsheets)
    kind: BlockKind
    text: str
    level: int = 0  # heading level (0 = title, 1..6)
    table: int | None = None  # rows of the same table share an id (kept intact by the chunker)
    table_header: str | None = None  # rendered header, repeated at the top of each table chunk


@dataclass
class ParsedDoc:
    blocks: list[Block]
    pages: int
    flagged_pages: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "pages": self.pages,
            "flagged_pages": self.flagged_pages,
            "notes": self.notes,
            "blocks": [asdict(b) for b in self.blocks],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ParsedDoc":
        return cls(
            blocks=[Block(**b) for b in data["blocks"]],
            pages=data["pages"],
            flagged_pages=list(data.get("flagged_pages", [])),
            notes=list(data.get("notes", [])),
        )


_ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿ]")
# Signs of broken Urdu extraction: replacement chars, private-use glyphs (InPage/Nastaleeq font
# maps), and Arabic presentation forms (glyph-level text, often reversed / unjoinable).
_BAD = re.compile(r"[�-ﭐ-﷿ﹰ-﻿]")
BAD_RATIO_LIMIT = 0.05


def urdu_quality(text: str) -> tuple[bool, float]:
    """(is_bad, bad_ratio) for a page of extracted text. Latin-only text is never 'bad' here."""
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return False, 0.0
    bad = len(_BAD.findall(text))
    urdu = len(_ARABIC_SCRIPT.findall(text))
    if bad == 0 and urdu == 0:
        return False, 0.0
    ratio = bad / max(bad + urdu, 1)
    return ratio > BAD_RATIO_LIMIT, round(ratio, 4)
