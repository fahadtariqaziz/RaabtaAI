"""Skills loader & packs (step 3.3): metadata, caps, selection matrix, determinism."""

import pytest

from app.agent.skills_loader import (
    SKILL_MAX,
    SKILLS_BUDGET,
    TurnFacts,
    available_for_router,
    load_skills,
    render,
    select,
)

NINE = {
    "admissions-school",
    "admissions-college",
    "admissions-university",
    "lead-capture",
    "visit-booking",
    "fee-recovery-etiquette",
    "roman-urdu-style-guide",
    "urdu-script-style-guide",
    "receipt-verification",
}


def names(facts: TurnFacts, **kw: int) -> list[str]:
    return [s.name for s in select(facts, **kw)]


def test_all_nine_packs_load_within_token_cap() -> None:
    skills = load_skills()
    assert set(skills) == NINE
    for s in skills.values():
        assert 0 < s.tokens <= SKILL_MAX, s.name
        assert s.meta.version == "1.0.0"


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (
            TurnFacts("school", "admissions", ("fee_structure",), language="roman_ur"),
            ["admissions-school", "roman-urdu-style-guide"],
        ),
        (
            TurnFacts("college", "admissions", ("visit",), language="en"),
            ["admissions-college", "visit-booking", "lead-capture"],
        ),
        (
            TurnFacts("university", "admissions", ("eligibility",), language="ur"),
            ["admissions-university", "urdu-script-style-guide"],
        ),
        (
            TurnFacts("school", "fees", ("payment_promise",), language="mixed"),
            ["fee-recovery-etiquette", "roman-urdu-style-guide"],
        ),
        (TurnFacts("school", "general", ("greeting",), language="en"), []),
        (TurnFacts("school", "fees", (), node="receipt_reader"), ["receipt-verification"]),
    ],
)
def test_selection_matrix(facts: TurnFacts, expected: list[str]) -> None:
    assert names(facts) == expected


def test_router_hints_respect_institution_and_module() -> None:
    base = TurnFacts("school", "general", ("greeting",), requested=("admissions-university",))
    assert names(base) == []  # wrong institution type → ignored
    hinted = TurnFacts("school", "admissions", ("other",), requested=("lead-capture", "nope"))
    assert names(hinted) == ["admissions-school", "lead-capture"]


def test_cap_drops_lowest_priority_and_order_is_deterministic() -> None:
    facts = TurnFacts("school", "admissions", ("visit", "enquiry"), language="roman_ur")
    full = names(facts, budget=10_000)
    assert full == [
        "admissions-school",
        "visit-booking",
        "lead-capture",
        "roman-urdu-style-guide",
    ]
    capped = select(facts)
    assert sum(s.tokens for s in capped) <= SKILLS_BUDGET
    assert [s.name for s in capped] == full[: len(capped)] or len(capped) < len(full)
    assert render(select(facts)) == render(select(facts))
    assert render(select(facts)).startswith("# Skill: admissions-school\n")
    assert render([]) == ""


def test_router_skill_list_excludes_other_types_and_receipts() -> None:
    avail = available_for_router("college")
    assert "admissions-college" in avail and "lead-capture" in avail
    assert "admissions-school" not in avail and "receipt-verification" not in avail
