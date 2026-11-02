"""Deterministic spreadsheet → facts mapping (step 2.6.5): when an XLSX/CSV sheet has recognizable
columns, rows become `fee_items` / `transport_routes` (pending) with no LLM involved. Amounts are
parsed by `app.kb.pkr`; rows whose amount can't be parsed are skipped and reported."""

import re
from dataclasses import dataclass, field
from typing import Any

from app.kb.parsers.tables import Table, read_tables
from app.kb.pkr import parse_frequency, parse_pkr


def _find(header: list[str], *patterns: str) -> int | None:
    for i, name in enumerate(header):
        low = name.lower()
        if any(re.search(p, low) for p in patterns):
            return i
    return None


@dataclass
class TableFacts:
    fee_items: list[dict[str, Any]] = field(default_factory=list)
    transport_routes: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    academic_year: str | None = None


_YEAR = re.compile(r"(20\d\d)\s*[-–/]\s*(\d{2,4})")
_TERM = re.compile(r"\b(fall|spring|summer)\s+(20\d\d)\b", re.IGNORECASE)


def _academic_year(table: Table) -> str | None:
    for title in table.titles:
        m = _YEAR.search(title)
        if m:
            return f"{m.group(1)}-{m.group(2)[-2:]}"
        t = _TERM.search(title)
        if t:
            return f"{t.group(1).title()} {t.group(2)}"
    return None


def _get(row: list[object], idx: int | None) -> object:
    return row[idx] if idx is not None and idx < len(row) else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def map_tables(tables: list[Table]) -> TableFacts:
    out = TableFacts()
    for table in tables:
        h = table.header
        year = _academic_year(table)
        out.academic_year = out.academic_year or year
        amount = _find(h, r"amount", r"fee\b.*pkr", r"\bpkr\b", r"\brs\b", r"rupees", r"fee \(")
        head = _find(h, r"fee head", r"\bhead\b", r"particular", r"description", r"charges? type")
        route = _find(h, r"\broute\b")
        if route is not None and amount is not None:
            areas = _find(h, r"area", r"stops?", r"covered")
            for n, row in enumerate(table.rows, start=1):
                value = parse_pkr(_get(row, amount))
                name = _text(_get(row, route))
                if value is None or name is None:
                    out.skipped.append(f"{table.sheet} row {n}: no route/amount")
                    continue
                out.transport_routes.append(
                    {
                        "name": name,
                        "areas": _text(_get(row, areas)),
                        "monthly_pkr": value,
                        "academic_year": year,
                        "source_page": table.index,
                        "source_quote": " | ".join(str(v) for v in row if v not in (None, "")),
                    }
                )
            continue
        if amount is None or head is None:
            continue
        cls = _find(h, r"\bclass\b", r"grade")
        prog = _find(h, r"program", r"programme", r"degree", r"course", r"group")
        freq = _find(h, r"frequen", r"period", r"per\b", r"payable")
        notes = _find(h, r"note", r"remark", r"comment")
        for n, row in enumerate(table.rows, start=1):
            value = parse_pkr(_get(row, amount))
            head_text = _text(_get(row, head))
            frequency = parse_frequency(_get(row, freq), parse_frequency(head_text, "one_time"))
            if value is None or head_text is None:
                out.skipped.append(f"{table.sheet} row {n}: amount not a single PKR value")
                continue
            out.fee_items.append(
                {
                    "class_name": _text(_get(row, cls)),
                    "program_name": _text(_get(row, prog)),
                    "head": head_text,
                    "amount_pkr": value,
                    "frequency": frequency,
                    "notes": _text(_get(row, notes)),
                    "academic_year": year,
                    "source_page": table.index,
                    "source_quote": " | ".join(str(v) for v in row if v not in (None, "")),
                }
            )
    for item in (*out.fee_items, *out.transport_routes):
        item["academic_year"] = item["academic_year"] or out.academic_year
    return out


def facts_from_spreadsheet(kind: str, data: bytes) -> TableFacts:
    return map_tables(read_tables(kind, data))
