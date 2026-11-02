"""PDF → page-aware blocks with permissively-licensed libraries (I-11: PyMuPDF is AGPL):

- **pdfplumber** (MIT, on pdfminer.six) — layout: words with font size/name → lines, headings
  (font ≥ 1.2× the body size, or short all-bold lines), and ruled tables (`find_tables`) → one row
  block per table row, header = first row.
- **pypdfium2** (Apache-2.0 / BSD-3, PDFium) — the *text* of any line containing Arabic script,
  read from that line's bounding box in logical order (pdfminer returns Urdu reversed, as
  presentation forms or NULs), and page rendering for vision OCR.

Each page gets the Urdu-quality check (`urdu_quality`: broken glyphs or fragmented Nastaliq) and the
scanned-page check; flagged pages go to the optional vision-OCR fallback (`app.kb.ocr`).
"""

import io
import itertools
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pdfplumber
import pypdfium2 as pdfium

from app.kb.parsers.base import Block, ParsedDoc, ParseError, urdu_quality

HEADING_RATIO = 1.2
MIN_PAGE_CHARS = 30  # fewer extracted characters on a page with images → probably scanned
LINE_TOLERANCE = 3.0  # points: words whose tops differ less than this share a line
_NEEDS_PDFIUM = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿\x00]")


@dataclass
class _Line:
    top: float
    bottom: float
    x0: float
    x1: float
    text: str
    size: float
    bold: bool


@dataclass
class _Table:
    top: float
    rows: list[list[str]]


def _group_lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - word["top"]) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _inside(word: dict[str, Any], boxes: list[tuple[float, float, float, float]]) -> bool:
    cx, cy = (word["x0"] + word["x1"]) / 2, (word["top"] + word["bottom"]) / 2
    return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)


def _clean(text: str) -> str:
    return " ".join(text.replace("\x00", "").split())


def _page_layout(page: Any, textpage: pdfium.PdfTextPage) -> tuple[list[_Line], list[_Table], bool]:
    height = float(page.height)
    tables = page.find_tables()
    boxes = [tuple(t.bbox) for t in tables]
    words = [
        w
        for w in page.extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False)
        if not _inside(w, boxes)
    ]
    lines: list[_Line] = []
    for group in _group_lines(words):
        x0 = min(w["x0"] for w in group)
        x1 = max(w["x1"] for w in group)
        top = min(w["top"] for w in group)
        bottom = max(w["bottom"] for w in group)
        text = " ".join(w["text"] for w in sorted(group, key=lambda w: w["x0"]))
        if _NEEDS_PDFIUM.search(text):  # Urdu: logical-order text from PDFium for this box
            text = textpage.get_text_bounded(
                left=x0 - 1, bottom=height - bottom - 1, right=x1 + 1, top=height - top + 1
            )
        text = _clean(text)
        if text:
            lines.append(
                _Line(
                    top=top,
                    bottom=bottom,
                    x0=x0,
                    x1=x1,
                    text=text,
                    size=round(max(float(w["size"]) for w in group), 1),
                    bold=all("bold" in str(w["fontname"]).lower() for w in group),
                )
            )
    parsed_tables = []
    for table in tables:
        rows = [[_clean(c or "") for c in row] for row in table.extract()]
        rows = [r for r in rows if any(r)]
        if rows:
            parsed_tables.append(_Table(top=float(table.bbox[1]), rows=rows))
    return lines, parsed_tables, bool(page.images)


def _body_size(pages: list[list[_Line]]) -> float:
    weights: Counter[float] = Counter()
    for lines in pages:
        for line in lines:
            weights[line.size] += len(line.text)
    if not weights:
        return 11.0
    return statistics.median_high(list(weights.elements()))


def _flush(blocks: list[Block], para: list[str], page_no: int) -> None:
    if para:
        blocks.append(Block(page=page_no, kind="para", text=" ".join(para)))
        para.clear()


def parse_pdf(data: bytes) -> ParsedDoc:
    try:
        plumber = pdfplumber.open(io.BytesIO(data))
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:  # pdfminer/pdfium raise many types for corrupt/encrypted files
        raise ParseError(f"cannot open PDF: {exc}") from None
    try:
        layouts = []
        for i, page in enumerate(plumber.pages):
            textpage = pdf[i].get_textpage()
            layouts.append(_page_layout(page, textpage))
    except Exception as exc:
        raise ParseError(f"cannot read PDF: {exc}") from None
    finally:
        plumber.close()
        pdf.close()

    body = _body_size([lines for lines, _, _ in layouts])
    blocks: list[Block] = []
    flagged: list[int] = []
    notes: list[str] = []
    table_no = 0
    for page_no, (lines, tables, has_images) in enumerate(layouts, start=1):
        page_text = "\n".join(line.text for line in lines) + "\n".join(
            " ".join(r) for t in tables for r in t.rows
        )
        bad, ratio = urdu_quality(page_text)
        if bad:
            flagged.append(page_no)
            notes.append(f"page {page_no}: broken Urdu text (score {ratio})")
        elif len(page_text.strip()) < MIN_PAGE_CHARS and has_images:
            flagged.append(page_no)
            notes.append(f"page {page_no}: little text on an image page (scanned?)")
        items: list[tuple[float, _Line | _Table]] = [(ln.top, ln) for ln in lines]
        items += [(t.top, t) for t in tables]
        para: list[str] = []
        last_bottom = 0.0
        last_heading: _Line | None = None
        gaps = [
            b.top - a.bottom
            for a, b in itertools.pairwise(lines)
            if 0 < b.top - a.bottom < a.size * 3
        ]
        para_gap = max(statistics.median(gaps) * 1.6, 2.0) if gaps else 6.0

        for _, item in sorted(items, key=lambda x: x[0]):
            if isinstance(item, _Table):
                _flush(blocks, para, page_no)
                table_no += 1
                header = [h or f"Column {j + 1}" for j, h in enumerate(item.rows[0])]
                for row in item.rows[1:]:
                    text = " | ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False) if v)
                    if text:
                        blocks.append(
                            Block(
                                page=page_no,
                                kind="row",
                                text=text,
                                table=table_no,
                                table_header=" | ".join(header),
                            )
                        )
                continue
            line = item
            is_heading = len(line.text) <= 120 and (
                line.size >= body * HEADING_RATIO
                or (line.bold and len(line.text) <= 80 and not line.text.endswith("."))
            )
            if is_heading:
                _flush(blocks, para, page_no)
                level = 1 if line.size >= body * 1.5 else 2
                wrapped = (
                    last_heading is not None
                    and blocks
                    and blocks[-1].kind == "heading"
                    and last_heading.size == line.size
                    and line.top - last_heading.bottom < line.size
                )
                if wrapped:  # a long heading wrapped onto the next line
                    blocks[-1].text = f"{blocks[-1].text} {line.text}"
                else:
                    blocks.append(Block(page=page_no, kind="heading", text=line.text, level=level))
                last_heading = line
            else:
                if para and line.top - last_bottom > para_gap:  # paragraph gap
                    _flush(blocks, para, page_no)
                para.append(line.text)
                last_heading = None
            last_bottom = line.bottom
        _flush(blocks, para, page_no)
    return ParsedDoc(blocks=blocks, pages=len(layouts), flagged_pages=flagged, notes=notes)


def render_page_png(data: bytes, page_no: int, dpi: int = 150) -> bytes:
    """Rasterize one page (1-based) for vision OCR (PDFium + Pillow)."""
    pdf = pdfium.PdfDocument(data)
    try:
        image = pdf[page_no - 1].render(scale=dpi / 72).to_pil()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()
