"""Step 2.2 — parsers: page numbers, headings, tables, Urdu round-trip, quality flags, sniffing."""

import io

import pymupdf
import pytest
from docx import Document as new_docx  # noqa: N813
from openpyxl import Workbook

from app.kb.parsers import parse
from app.kb.parsers.base import ParsedDoc, ParseError, urdu_quality
from app.kb.sniff import UnsupportedFileError, sniff
from app.seeds.schema import SEEDS_DIR

ABC = SEEDS_DIR / "abc_grammar_school" / "docs"


def _pdf(pages: list[list[tuple[str, float]]], image_page: bool = False) -> bytes:
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 72.0
        for text, size in lines:
            page.insert_text((72, y), text, fontsize=size)
            y += size * 1.8
    if image_page:
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
        pix.clear_with(200)
        page.insert_image(pymupdf.Rect(72, 72, 300, 300), pixmap=pix)
    data: bytes = doc.tobytes()
    doc.close()
    return data


def test_pdf_pages_and_headings() -> None:
    data = _pdf(
        [
            [("Admission Policy", 20), ("Forms are available at the office.", 11)],
            [("Fee Schedule", 20), ("Monthly tuition is billed in advance.", 11)],
        ]
    )
    parsed = parse("pdf", data)
    assert parsed.pages == 2
    heads = [(b.page, b.text) for b in parsed.blocks if b.kind == "heading"]
    assert heads == [(1, "Admission Policy"), (2, "Fee Schedule")]
    paras = [(b.page, b.text) for b in parsed.blocks if b.kind == "para"]
    assert (2, "Monthly tuition is billed in advance.") in paras
    assert parsed.flagged_pages == []


def test_pdf_image_only_page_is_flagged() -> None:
    parsed = parse("pdf", _pdf([[("Welcome", 11), ("Some text on page one.", 11)]], True))
    assert parsed.flagged_pages == [2]
    assert "scanned" in parsed.notes[0]


def test_corrupt_pdf_raises() -> None:
    with pytest.raises(ParseError):
        parse("pdf", b"%PDF-1.7 this is not really a pdf")


def test_seed_docx_headings_tables_and_urdu_round_trip() -> None:
    parsed = parse("docx", (ABC / "prospectus.docx").read_bytes())
    heads = [b.text for b in parsed.blocks if b.kind == "heading"]
    assert heads[0].startswith("ABC Grammar School")
    assert "School timings" in heads
    assert "داخلہ کا طریقہ کار" in heads  # Urdu heading survives intact
    urdu = [b.text for b in parsed.blocks if "داخلہ فارم" in b.text]
    assert urdu and urdu[0].startswith("داخلہ فارم اسکول کے دفتر")
    rows = [b for b in parsed.blocks if b.kind == "row"]
    assert rows and rows[0].text.startswith("Event: ") and "| Date: " in rows[0].text
    assert all(b.page == 1 for b in parsed.blocks)


def test_docx_page_breaks_advance_pages() -> None:
    doc = new_docx()
    doc.add_heading("One", level=1)
    doc.add_paragraph("first page")
    doc.add_page_break()
    doc.add_heading("Two", level=1)
    doc.add_paragraph("second page")
    buf = io.BytesIO()
    doc.save(buf)
    parsed = parse("docx", buf.getvalue())
    pages = {b.text: b.page for b in parsed.blocks}
    assert pages["first page"] == 1
    assert pages["Two"] == 2


def test_seed_xlsx_rows_are_self_describing() -> None:
    parsed = parse("xlsx", (ABC / "fee_structure.xlsx").read_bytes())
    assert parsed.pages == 2  # two sheets
    rows = [b for b in parsed.blocks if b.kind == "row"]
    assert "Class: Class 5 | Fee head: Tuition fee | Amount (PKR): 12,500 | Frequency: Monthly" in [
        r.text for r in rows
    ]
    transport = [r for r in rows if r.page == 2]
    assert transport[0].text.startswith("Route: DHA | Areas covered: ")
    assert len({r.table for r in rows}) == 2


def test_csv_with_semicolons() -> None:
    data = b"Class;Fee head;Amount\nClass 1;Tuition fee;11500\n"
    parsed = parse("csv", data)
    assert [b.text for b in parsed.blocks if b.kind == "row"] == [
        "Class: Class 1 | Fee head: Tuition fee | Amount: 11,500"
    ]


def test_parsed_doc_json_round_trip() -> None:
    parsed = parse("xlsx", (ABC / "fee_structure.xlsx").read_bytes())
    assert ParsedDoc.from_json(parsed.to_json()) == parsed


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ("Admission is open for all classes.", False),
        ("داخلہ فارم اسکول کے دفتر سے حاصل کیا جا سکتا ہے۔", False),
        ("ﺩﺍﺧﻠﮧ ﻓﺎﺭﻡ ﺍﺳﮑﻮﻝ", True),  # presentation forms (glyph-level extraction)
        (" abc ", True),  # private-use glyphs (InPage fonts)
        ("داخلہ ��� فارم", True),  # replacement chars
    ],
)
def test_urdu_quality(text: str, bad: bool) -> None:
    assert urdu_quality(text)[0] is bad


def test_sniff_accepts_supported_and_rejects_others() -> None:
    assert sniff((ABC / "prospectus.docx").read_bytes(), "x.bin").kind == "docx"
    assert sniff((ABC / "fee_structure.xlsx").read_bytes(), "fees").kind == "xlsx"
    assert sniff(b"%PDF-1.4\n...", "a.pdf").kind == "pdf"
    assert sniff(b"a,b\n1,2\n", "list.csv").kind == "csv"
    wb = Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    assert sniff(buf.getvalue(), "renamed.pdf").kind == "xlsx"  # content wins over extension
    for data, name in [
        (b"MZ\x90\x00\x03" + b"\x00" * 100, "setup.exe"),
        (b"MZ\x90\x00", "fees.pdf"),
        (b"PK\x03\x04garbage", "x.docx"),
        (b"\x89PNG\r\n\x1a\n", "photo.png"),
        (b"a,b\n1,2\n", "notes.txt"),
        (b"", "empty.csv"),
    ]:
        with pytest.raises(UnsupportedFileError):
            sniff(data, name)
