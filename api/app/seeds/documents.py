"""Build each demo institution's source documents from seed.yaml (fee XLSX + prospectus DOCX).
They are the inputs Phase 2 ingestion parses; numbers in them come from the same YAML as the
expected facts, so evals can compare exactly."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from openpyxl import Workbook
from openpyxl.styles import Font

from app.seeds.schema import SeedFile

FEE_XLSX = "fee_structure.xlsx"
PROSPECTUS_DOCX = "prospectus.docx"

_FREQ = {
    "one_time": "One time",
    "monthly": "Monthly",
    "annual": "Annual",
    "per_semester": "Per semester",
}


def build_fee_xlsx(seed: SeedFile, path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None  # noqa: S101 (new workbook always has a sheet)
    ws.title = "Fee structure"
    label = "Class" if seed.institution.type == "school" else "Program"
    ws.append([f"{seed.institution.name} — Fee structure {seed.facts.academic_year}"])
    ws.append([label, "Fee head", "Amount (PKR)", "Frequency", "Notes"])
    for cell in ws[2]:
        cell.font = Font(bold=True)
    for item in seed.facts.fee_items:
        ws.append(
            [
                item.class_name or item.program,
                item.head,
                item.amount_pkr,
                _FREQ[item.frequency],
                item.notes or "",
            ]
        )
    if seed.facts.transport_routes:
        tr = wb.create_sheet("Transport")
        tr.append(["Route", "Areas covered", "Monthly fee (PKR)"])
        for cell in tr[1]:
            cell.font = Font(bold=True)
        for route in seed.facts.transport_routes:
            tr.append([route.name, route.areas, route.monthly_pkr])
    wb.save(path)


def build_prospectus_docx(seed: SeedFile, path: Path) -> None:
    doc = Document()
    doc.add_heading(seed.prospectus.title, level=0)
    for section in seed.prospectus.sections:
        heading = doc.add_heading(section.heading, level=1)
        rtl = section.lang == "ur"
        if rtl:
            heading.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for line in section.body.strip().splitlines():
            para = doc.add_paragraph(line.strip())
            if rtl:
                para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if seed.facts.key_dates:
        doc.add_heading("Important dates", level=1)
        table = doc.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Event", "Date"
        for kd in seed.facts.key_dates:
            row = table.add_row().cells
            row[0].text = kd.event + (f" ({kd.notes})" if kd.notes else "")
            row[1].text = kd.date.strftime("%d %B %Y")
    doc.save(str(path))


def ensure_documents(seed: SeedFile, directory: Path, *, force: bool = False) -> list[Path]:
    """Create docs/ files if missing (or always with force). Returns the document paths."""
    docs = directory / "docs"
    docs.mkdir(exist_ok=True)
    fee, prospectus = docs / FEE_XLSX, docs / PROSPECTUS_DOCX
    if force or not fee.exists():
        build_fee_xlsx(seed, fee)
    if force or not prospectus.exists():
        build_prospectus_docx(seed, prospectus)
    return [fee, prospectus]
