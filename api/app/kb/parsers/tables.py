"""XLSX/CSV → tables with a detected header row; rendered as `Header: value | …` rows so each row
is a self-describing retrieval unit. `read_tables` is shared with the deterministic facts mapper."""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

from openpyxl import load_workbook

from app.kb.parsers.base import Block, ParsedDoc, ParseError


@dataclass
class Table:
    sheet: str
    index: int  # 1-based sheet number (used as "page")
    titles: list[str]  # single-cell rows above the header (e.g. "Fee structure 2026-27")
    header: list[str]
    rows: list[list[object]]


def _cell(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        # CSV numbers arrive as text; keep ids/phones with a leading zero as text
        plain = value.replace(",", "")
        if plain.isdigit() and not plain.startswith("0") and len(plain) <= 12:
            return int(plain)
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, datetime):
        return value.strftime("%d %B %Y") if value.time() == datetime.min.time() else str(value)
    if isinstance(value, date):
        return value.strftime("%d %B %Y")
    return str(value)


def _split(name: str, index: int, raw_rows: list[list[object]]) -> Table:
    rows = [[_cell(v) for v in r] for r in raw_rows]
    rows = [r for r in rows if any(v not in (None, "") for v in r)]
    width = max((sum(v not in (None, "") for v in r) for r in rows), default=0)
    titles: list[str] = []
    header: list[str] = []
    body: list[list[object]] = []
    for i, row in enumerate(rows):
        filled = sum(v not in (None, "") for v in row)
        if filled >= max(2, round(0.6 * width)) and all(
            isinstance(v, str) or v in (None, "") for v in row
        ):
            header = [fmt(v) or f"Column {j + 1}" for j, v in enumerate(row)]
            body = rows[i + 1 :]
            break
        titles.append(" ".join(fmt(v) for v in row if v not in (None, "")))
    else:
        header = [f"Column {j + 1}" for j in range(max((len(r) for r in rows), default=0))]
        body, titles = rows, []
    return Table(sheet=name, index=index, titles=titles, header=header, rows=body)


def read_tables(kind: str, data: bytes) -> list[Table]:
    if kind == "xlsx":
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise ParseError(f"cannot open spreadsheet: {exc}") from None
        tables = []
        for i, ws in enumerate(wb.worksheets, start=1):
            tables.append(_split(ws.title, i, [list(r) for r in ws.iter_rows(values_only=True)]))
        wb.close()
        return tables
    if kind == "csv":
        text = data.decode("utf-8-sig", errors="replace")
        try:
            dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(text[:4096], ",;\t")
        except csv.Error:
            dialect = csv.excel
        raw: list[list[object]] = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
        return [_split("CSV", 1, raw)]
    raise ParseError(f"not a table file: {kind}")


def render_row(header: list[str], row: list[object]) -> str:
    parts = []
    for name, value in zip(header, row, strict=False):
        text = fmt(value)
        if text:
            parts.append(f"{name}: {text}")
    return " | ".join(parts)


def parse_table_file(kind: str, data: bytes) -> ParsedDoc:
    tables = read_tables(kind, data)
    blocks: list[Block] = []
    for t_no, table in enumerate(tables, start=1):
        heading = " — ".join([table.sheet, *table.titles]) if table.titles else table.sheet
        blocks.append(Block(page=table.index, kind="heading", text=heading, level=1))
        header_text = " | ".join(table.header)
        for row in table.rows:
            text = render_row(table.header, row)
            if text:
                blocks.append(
                    Block(
                        page=table.index,
                        kind="row",
                        text=text,
                        table=t_no,
                        table_header=header_text,
                    )
                )
    return ParsedDoc(blocks=blocks, pages=len(tables))
