"""Step 2.6 — deterministic money parsing, spreadsheet→facts mapping (exact vs seed.yaml), and the
Opus extractor's normalization + cassette record/replay (no network)."""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from app.kb.facts_extractor import (
    FactsBatch,
    XFee,
    XKeyDate,
    XProgram,
    XRoute,
    XScholarship,
    batches,
    extract_facts,
)
from app.kb.facts_tables import facts_from_spreadsheet
from app.kb.parsers import parse
from app.kb.pkr import parse_frequency, parse_pkr
from app.llm.claude import CassetteMissingError, ClaudeClient, ParseResult
from app.seeds.schema import load_seed, seed_dirs


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rs. 12,500/-", 12500),
        ("PKR 1.45 lac", 145000),
        ("1,45,000", 145000),
        ("15k", 15000),
        ("Rs 25 hazar", 25000),
        ("2 لاکھ", 200000),
        (9500, 9500),
        (9500.0, 9500),
        ("Free", None),
        ("10,000–15,000", None),
        (None, None),
        (-5, None),
    ],
)
def test_parse_pkr(raw: object, expected: int | None) -> None:
    assert parse_pkr(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Monthly", "monthly"),
        ("per semester", "per_semester"),
        ("One time", "one_time"),
        ("Annual", "annual"),
        ("ماہانہ", "monthly"),
        (None, None),
    ],
)
def test_parse_frequency(raw: str | None, expected: str | None) -> None:
    assert parse_frequency(raw) == expected


@pytest.mark.parametrize("directory", seed_dirs(), ids=lambda d: d.name)
def test_seed_spreadsheets_map_exactly_to_seed_yaml(directory: Path) -> None:
    seed = load_seed(directory)
    mapped = facts_from_spreadsheet(
        "xlsx", (directory / "docs" / "fee_structure.xlsx").read_bytes()
    )
    expected_fees = [
        (f.class_name, f.program, f.head, f.amount_pkr, f.frequency) for f in seed.facts.fee_items
    ]
    got_fees = [
        (r["class_name"], r["program_name"], r["head"], r["amount_pkr"], r["frequency"])
        for r in mapped.fee_items
    ]
    assert got_fees == expected_fees
    assert [(r["name"], r["monthly_pkr"]) for r in mapped.transport_routes] == [
        (t.name, t.monthly_pkr) for t in seed.facts.transport_routes
    ]
    assert mapped.skipped == []
    assert all(r["source_page"] in (1, 2) for r in mapped.fee_items + mapped.transport_routes)


def _canned() -> FactsBatch:
    return FactsBatch(
        academic_year="Fall 2027",
        fee_items=[
            XFee(
                class_name=None,
                program_name="BS Computer Science",
                head="Tuition fee",
                amount_text="PKR 145,000",
                frequency_text="per semester",
                notes=None,
                page=1,
                quote="BS Computer Science PKR 145,000",
            ),
            XFee(
                class_name=None,
                program_name="BBA",
                head="Tuition fee",
                amount_text="as per notice",
                frequency_text=None,
                notes=None,
                page=1,
                quote="?",
            ),
        ],
        programs=[
            XProgram(
                name="BBA",
                level="undergraduate",
                duration="4 years",
                eligibility="Intermediate 45%",
                deadline="2027-07-15",
                seats=150,
                page=1,
                quote="BBA PKR 120,000",
            )
        ],
        key_dates=[
            XKeyDate(
                event="Last date to apply",
                date="2027-07-15",
                end_date=None,
                notes=None,
                page=1,
                quote="Last date to apply",
            ),
            XKeyDate(
                event="Merit list", date="late July", end_date=None, notes=None, page=1, quote="?"
            ),
        ],
        scholarships=[
            XScholarship(
                name="Merit scholarship",
                rule="admission merit",
                amount="25% to 75%",
                page=99,
                quote="Merit scholarships",
            )
        ],
        transport_routes=[
            XRoute(
                name="Bahria Town",
                areas="Bahria Town, Lake City",
                monthly_text="Rs 6,500",
                page=1,
                quote="Bahria Town",
            )
        ],
    )


async def test_extractor_normalizes_and_replays_from_cassette(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_dir = next(d for d in seed_dirs() if d.name == "lits_university")
    parsed = parse("docx", (seed_dir / "docs" / "prospectus.docx").read_bytes())

    async def fake_live(self: ClaudeClient, node: str, *args: Any) -> ParseResult[FactsBatch]:
        return ParseResult(
            output=_canned(),
            model="claude-opus-5-5",
            effort="high",
            stop_reason="end_turn",
            input_tokens=1200,
            output_tokens=300,
        )

    monkeypatch.setattr(ClaudeClient, "_live", fake_live)
    recorded = await extract_facts(
        ClaudeClient("k", mode="record", cassette_dir=tmp_path), parsed, "LITS Admissions Guide"
    )
    assert len(list(tmp_path.rglob("*.json"))) == 1  # noqa: ASYNC240 (test, tiny dir)

    monkeypatch.undo()
    replayed = await extract_facts(
        ClaudeClient(None, mode="replay", cassette_dir=tmp_path), parsed, "LITS Admissions Guide"
    )
    assert replayed.rows == recorded.rows
    assert replayed.runs[0].replayed
    rows = replayed.rows
    assert [(f["program_name"], f["amount_pkr"], f["frequency"]) for f in rows["fee_items"]] == [
        ("BS Computer Science", 145000, "per_semester")
    ]
    assert rows["key_dates"] == [
        {
            "event": "Last date to apply",
            "date": dt.date(2027, 7, 15),
            "end_date": None,
            "notes": None,
            "academic_year": "Fall 2027",
            "source_page": 1,
            "source_quote": "Last date to apply",
        }
    ]
    assert rows["programs"][0]["deadline"] == dt.date(2027, 7, 15)
    assert rows["scholarships"][0]["source_page"] is None  # page 99 doesn't exist
    assert rows["transport_routes"][0]["monthly_pkr"] == 6500
    assert len(replayed.dropped) == 2  # unparseable amount + non-ISO date

    other = parse("docx", (seed_dir / "docs" / "prospectus.docx").read_bytes())
    with pytest.raises(CassetteMissingError):
        await extract_facts(
            ClaudeClient(None, mode="replay", cassette_dir=tmp_path / "x"),
            other,
            "LITS Admissions Guide",
        )


def test_page_batches_respect_limits() -> None:
    pages = {i: "word " * 100 for i in range(1, 46)}
    groups = batches(pages)
    assert [len(g) for g in groups] == [20, 20, 5]
    big = {1: "x" * 170_000, 2: "y"}
    assert [len(g) for g in batches(big)] == [1, 1]
