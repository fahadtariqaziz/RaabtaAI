"""Citation schema (step 2.7, PLAN §11 rule 3): every factual reply carries its sources.
Chunks cite `{document_id, title, page, chunk_id, quote}`; fact rows cite the document/page they
were extracted from (`chunk_id` None)."""

import re
import uuid

from pydantic import BaseModel, ConfigDict, Field

QUOTE_MAX = 240


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: uuid.UUID
    title: str
    page: int | None = None
    chunk_id: uuid.UUID | None = None
    quote: str | None = Field(default=None, max_length=QUOTE_MAX + 1)

    def label(self) -> str:
        """Short human source line, e.g. for WhatsApp: `ABC Prospectus, p. 3`."""
        return f"{self.title}, p. {self.page}" if self.page else self.title


def make_quote(text: str, terms: list[str] | None = None, limit: int = QUOTE_MAX) -> str:
    """The sentence/line that best matches `terms` (else the opening), trimmed to `limit`."""
    flat = re.sub(r"\s+", " ", text).strip()
    if terms:
        parts = re.split(r"(?<=[.!?۔])\s+|\s*\|\s*(?=[A-Z])", flat)
        lowered = [t.lower() for t in terms if t]
        best = max(parts, key=lambda p: sum(t in p.lower() for t in lowered), default=flat)
        if any(t in best.lower() for t in lowered):
            flat = best
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"
