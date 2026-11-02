"""PDF → page-aware blocks via PyMuPDF. Headings: lines whose font size is ≥ 1.2× the document's
body size (or short all-bold lines). Each page gets the Urdu-quality check; bad or image-only pages
are flagged (`ParsedDoc.flagged_pages`) for the optional vision-OCR fallback (`app.kb.ocr`)."""

import statistics
from collections import Counter
from dataclasses import dataclass

import pymupdf

from app.kb.parsers.base import Block, ParsedDoc, ParseError, urdu_quality

HEADING_RATIO = 1.2
MIN_PAGE_CHARS = 30  # fewer extracted characters on a page with images → probably scanned


@dataclass
class _Line:
    text: str
    size: float
    bold: bool


def _lines(page: pymupdf.Page) -> list[list[_Line]]:
    """Text blocks of a page, each a list of lines."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        lines = []
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            size = max(s["size"] for s in spans)
            bold = all(int(s["flags"]) & 16 for s in spans)
            lines.append(_Line(text=text, size=round(size, 1), bold=bold))
        if lines:
            out.append(lines)
    return out


def _body_size(pages: list[list[list[_Line]]]) -> float:
    weights: Counter[float] = Counter()
    for page in pages:
        for block in page:
            for line in block:
                weights[line.size] += len(line.text)
    if not weights:
        return 11.0
    return statistics.median_high(list(weights.elements()))


def parse_pdf(data: bytes) -> ParsedDoc:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ParseError(f"cannot open PDF: {exc}") from None
    with doc:
        if doc.needs_pass:
            raise ParseError("PDF is password-protected")
        loaded = [doc.load_page(i) for i in range(doc.page_count)]
        pages = [_lines(page) for page in loaded]
        has_images = [bool(page.get_images()) for page in loaded]
    body = _body_size(pages)
    blocks: list[Block] = []
    flagged: list[int] = []
    notes: list[str] = []
    for page_no, page_blocks in enumerate(pages, start=1):
        page_text = "\n".join(line.text for b in page_blocks for line in b)
        bad, ratio = urdu_quality(page_text)
        if bad:
            flagged.append(page_no)
            notes.append(f"page {page_no}: broken Urdu text (bad ratio {ratio})")
        elif len(page_text.strip()) < MIN_PAGE_CHARS and has_images[page_no - 1]:
            flagged.append(page_no)
            notes.append(f"page {page_no}: little text on an image page (scanned?)")
        for lines in page_blocks:
            para: list[str] = []
            for line in lines:
                is_heading = len(line.text) <= 120 and (
                    line.size >= body * HEADING_RATIO
                    or (line.bold and len(line.text) <= 80 and not line.text.endswith("."))
                )
                if is_heading:
                    if para:
                        blocks.append(Block(page=page_no, kind="para", text=" ".join(para)))
                        para = []
                    level = 1 if line.size >= body * 1.5 else 2
                    blocks.append(Block(page=page_no, kind="heading", text=line.text, level=level))
                else:
                    para.append(line.text)
            if para:
                blocks.append(Block(page=page_no, kind="para", text=" ".join(para)))
    return ParsedDoc(blocks=blocks, pages=len(pages), flagged_pages=flagged, notes=notes)


def render_page_png(data: bytes, page_no: int, dpi: int = 150) -> bytes:
    """Rasterize one page (1-based) for vision OCR."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pix = doc[page_no - 1].get_pixmap(dpi=dpi)
        png: bytes = pix.tobytes("png")
        return png
