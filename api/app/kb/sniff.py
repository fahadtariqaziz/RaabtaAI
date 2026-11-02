"""Upload type detection from content, not from the client's Content-Type (PLAN §18 Uploads).
Allowed: PDF, DOCX, XLSX, CSV. Everything else (executables, legacy .doc/.xls, archives, images)
is rejected."""

import io
import zipfile
from dataclasses import dataclass

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}


class UnsupportedFileError(ValueError):
    pass


@dataclass(frozen=True)
class Sniffed:
    kind: str
    mime: str


def _ooxml_kind(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return None
    if "[Content_Types].xml" not in names:
        return None
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    return None


def _looks_like_csv(data: bytes) -> bool:
    sample = data[:65536]
    if b"\x00" in sample:
        return False
    try:
        text = sample.decode("utf-8-sig")
    except UnicodeDecodeError:
        # a multi-byte char may be cut at the sample boundary
        try:
            text = sample[:-3].decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return bool(lines) and any(sep in lines[0] for sep in (",", ";", "\t"))


def sniff(data: bytes, filename: str) -> Sniffed:
    if not data:
        raise UnsupportedFileError("file is empty")
    if data.startswith(b"%PDF-"):
        kind = "pdf"
    elif data.startswith(b"PK\x03\x04"):
        found = _ooxml_kind(data)
        if found is None:
            raise UnsupportedFileError("zip file is not a DOCX or XLSX document")
        kind = found
    elif filename.lower().endswith(".csv") and _looks_like_csv(data):
        kind = "csv"
    else:
        raise UnsupportedFileError("unsupported file type (allowed: PDF, DOCX, XLSX, CSV)")
    return Sniffed(kind=kind, mime=MIME[kind])
