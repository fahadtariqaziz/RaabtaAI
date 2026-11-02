"""Document parsers (step 2.2): bytes → ordered `Block`s with page numbers and headings."""

from app.kb.parsers.base import Block, ParsedDoc, ParseError
from app.kb.parsers.docx import parse_docx
from app.kb.parsers.pdf import parse_pdf
from app.kb.parsers.tables import parse_table_file


def parse(kind: str, data: bytes) -> ParsedDoc:
    if kind == "pdf":
        return parse_pdf(data)
    if kind == "docx":
        return parse_docx(data)
    if kind in ("xlsx", "csv"):
        return parse_table_file(kind, data)
    raise ParseError(f"no parser for kind {kind!r}")


__all__ = ["Block", "ParseError", "ParsedDoc", "parse"]
