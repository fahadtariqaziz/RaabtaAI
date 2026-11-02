"""DOCX → blocks in body order (paragraphs and tables). Headings from paragraph styles
(`Title`, `Heading N`); tables → one row block each with the first row as header. DOCX has no fixed
pages: page = 1 + explicit/rendered page breaks seen so far."""

import io

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.kb.parsers.base import Block, ParsedDoc, ParseError

_BREAKS = ".//w:br[@w:type='page'] | .//w:lastRenderedPageBreak"


def _heading_level(par: Paragraph) -> int | None:
    name = (par.style.name if par.style is not None else "") or ""
    if name == "Title":
        return 0
    if name.startswith("Heading"):
        tail = name.removeprefix("Heading").strip()
        return int(tail) if tail.isdigit() else 1
    return None


def _cell_text(text: str) -> str:
    return " ".join(text.split())


def parse_docx(data: bytes) -> ParsedDoc:
    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ParseError(f"cannot open DOCX: {exc}") from None
    blocks: list[Block] = []
    page = 1
    table_no = 0
    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:p"):
            par = Paragraph(el, doc)
            text = par.text.strip()
            breaks = len(el.xpath(_BREAKS))
            if text:
                level = _heading_level(par)
                if level is None:
                    blocks.append(Block(page=page, kind="para", text=text))
                else:
                    blocks.append(Block(page=page, kind="heading", text=text, level=level))
            page += breaks
        elif el.tag == qn("w:tbl"):
            table = Table(el, doc)
            rows = [[_cell_text(c.text) for c in r.cells] for r in table.rows]
            rows = [r for r in rows if any(r)]
            if not rows:
                continue
            table_no += 1
            header = [h or f"Column {i + 1}" for i, h in enumerate(rows[0])]
            header_text = " | ".join(header)
            for row in rows[1:]:
                text = " | ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False) if v)
                if text:
                    blocks.append(
                        Block(
                            page=page,
                            kind="row",
                            text=text,
                            table=table_no,
                            table_header=header_text,
                        )
                    )
    return ParsedDoc(blocks=blocks, pages=page)
