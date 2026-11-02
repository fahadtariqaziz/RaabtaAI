"""Opus facts extraction at ingestion (step 2.6.2, PLAN §7 facts_extractor): effort high,
structured output `FactsBatch`, page-batched (≤ 20 pages and ≤ ~40k tokens per call), page refs +
quotes kept. The model transcribes amounts as text; `app.kb.pkr` turns them into integers
(no LLM arithmetic). Rows that don't normalize are dropped and reported."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.kb.parsers.base import ParsedDoc
from app.kb.pkr import parse_frequency, parse_pkr
from app.kb.text import estimate_tokens
from app.llm.claude import ClaudeClient, ParseResult
from app.prompts import load_prompt

MAX_PAGES = 20
FACT_KINDS = ("fee_items", "programs", "key_dates", "scholarships", "transport_routes")
MAX_TOKENS_PER_BATCH = 40_000


class XFee(BaseModel):
    class_name: str | None
    program_name: str | None
    head: str
    amount_text: str
    frequency_text: str | None
    notes: str | None
    page: int
    quote: str


class XProgram(BaseModel):
    name: str
    level: str | None
    duration: str | None
    eligibility: str | None
    deadline: str | None = Field(description="YYYY-MM-DD or null")
    seats: int | None
    page: int
    quote: str


class XKeyDate(BaseModel):
    event: str
    date: str = Field(description="YYYY-MM-DD")
    end_date: str | None
    notes: str | None
    page: int
    quote: str


class XScholarship(BaseModel):
    name: str
    rule: str | None
    amount: str | None
    page: int
    quote: str


class XRoute(BaseModel):
    name: str
    areas: str | None
    monthly_text: str
    page: int
    quote: str


class FactsBatch(BaseModel):
    academic_year: str | None
    fee_items: list[XFee]
    programs: list[XProgram]
    key_dates: list[XKeyDate]
    scholarships: list[XScholarship]
    transport_routes: list[XRoute]


@dataclass
class ExtractedFacts:
    rows: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {k: [] for k in FACT_KINDS}
    )
    dropped: list[str] = field(default_factory=list)
    runs: list[ParseResult[FactsBatch]] = field(default_factory=list)


def page_texts(parsed: ParsedDoc) -> dict[int, str]:
    pages: dict[int, list[str]] = {}
    for block in parsed.blocks:
        prefix = "#" * max(block.level, 1) + " " if block.kind == "heading" else ""
        pages.setdefault(block.page, []).append(prefix + block.text)
    return {p: "\n".join(lines) for p, lines in sorted(pages.items())}


def batches(pages: dict[int, str]) -> list[list[tuple[int, str]]]:
    out: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    tokens = 0
    for page, text in pages.items():
        t = estimate_tokens(text)
        if current and (len(current) >= MAX_PAGES or tokens + t > MAX_TOKENS_PER_BATCH):
            out.append(current)
            current, tokens = [], 0
        current.append((page, text))
        tokens += t
    if current:
        out.append(current)
    return out


def _iso(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def normalize_batch(batch: FactsBatch, valid_pages: set[int], out: ExtractedFacts) -> None:
    year = batch.academic_year

    def page(p: int) -> int | None:
        return p if p in valid_pages else None

    for f in batch.fee_items:
        amount = parse_pkr(f.amount_text)
        if amount is None:
            out.dropped.append(f"fee '{f.head}': amount '{f.amount_text}' not a single PKR value")
            continue
        out.rows["fee_items"].append(
            {
                "class_name": f.class_name,
                "program_name": f.program_name,
                "head": f.head,
                "amount_pkr": amount,
                "frequency": parse_frequency(f.frequency_text, parse_frequency(f.head, "one_time")),
                "notes": f.notes,
                "academic_year": year,
                "source_page": page(f.page),
                "source_quote": f.quote,
            }
        )
    for p in batch.programs:
        out.rows["programs"].append(
            {
                "name": p.name,
                "level": p.level,
                "duration": p.duration,
                "eligibility": p.eligibility,
                "deadline": _iso(p.deadline),
                "seats": p.seats,
                "academic_year": year,
                "source_page": page(p.page),
                "source_quote": p.quote,
            }
        )
    for d in batch.key_dates:
        when = _iso(d.date)
        if when is None:
            out.dropped.append(f"date '{d.event}': '{d.date}' is not YYYY-MM-DD")
            continue
        out.rows["key_dates"].append(
            {
                "event": d.event,
                "date": when,
                "end_date": _iso(d.end_date),
                "notes": d.notes,
                "academic_year": year,
                "source_page": page(d.page),
                "source_quote": d.quote,
            }
        )
    for s in batch.scholarships:
        out.rows["scholarships"].append(
            {
                "name": s.name,
                "rule": s.rule,
                "amount": s.amount,
                "academic_year": year,
                "source_page": page(s.page),
                "source_quote": s.quote,
            }
        )
    for r in batch.transport_routes:
        fare = parse_pkr(r.monthly_text)
        if fare is None:
            out.dropped.append(f"route '{r.name}': fare '{r.monthly_text}' not a PKR value")
            continue
        out.rows["transport_routes"].append(
            {
                "name": r.name,
                "areas": r.areas,
                "monthly_pkr": fare,
                "academic_year": year,
                "source_page": page(r.page),
                "source_quote": r.quote,
            }
        )


async def extract_facts(client: ClaudeClient, parsed: ParsedDoc, title: str) -> ExtractedFacts:
    prompt = load_prompt("facts_extractor")
    pages = page_texts(parsed)
    out = ExtractedFacts()
    for batch in batches(pages):
        body = "\n\n".join(f"=== Page {p} ===\n{text}" for p, text in batch)
        result = await client.parse(
            "facts_extractor",
            system=prompt.text,
            messages=[
                {
                    "role": "user",
                    "content": f"Document title: {title}\n\n<document>\n{body}\n</document>",
                }
            ],
            output_format=FactsBatch,
        )
        out.runs.append(result)
        normalize_batch(result.output, {p for p, _ in batch}, out)
    return out
