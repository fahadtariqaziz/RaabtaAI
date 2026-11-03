"""Prompt files & loader (step 3.2)."""

import re

import pytest

from app.agent.phrases import PHRASES, phrase
from app.core.models_registry import spec_for
from app.prompts import (
    PromptError,
    _validate,
    all_prompts,
    load_prompt,
    render_tenant_block,
    tenant_block_version,
)

EXPECTED = {
    "system_global",
    "agent_admissions",
    "agent_fees",
    "router",
    "guard_in",
    "answer_check",
    "tone_check",
    "summarizer",
    "facts_extractor",
    "judge_admissions",
}
DATE_LIKE = re.compile(
    r"\b20\d\d-\d\d-\d\d\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\btoday is\b|\b\d{1,2}:\d\d:\d\d\b", re.I
)
ARABIC = re.compile(r"[\u0600-\u06FF]")

TENANT = {
    "name": "ABC Grammar School",
    "type": "school",
    "city": "Lahore",
    "languages": ["en", "ur", "roman_ur"],
    "academic_year": "2026-27",
    "cta": "book a campus visit",
    "details": {"phone": "+92 42 3575 1100", "address": "45-B Gulberg III", "office_hours": "x"},
    "facts_version": 7,
}


def test_all_prompt_files_load_with_valid_front_matter() -> None:
    prompts = {p.name: p for p in all_prompts()}
    assert set(prompts) == EXPECTED
    for p in prompts.values():
        assert re.match(r"^\d+\.\d+\.\d+$", p.version)
        assert len(p.hash) == 16 and p.text
        if p.model_key != "agent":
            assert spec_for(p.model_key)  # type: ignore[arg-type]


def test_cacheable_prompts_have_no_dates_or_timestamps() -> None:
    for p in all_prompts():
        if p.cacheable:
            assert not DATE_LIKE.search(p.text), f"{p.name}: date/timestamp in cached prompt"


def test_router_has_twelve_examples_and_valid_json_lines() -> None:
    text = load_prompt("router").text
    examples = re.findall(r"^\d+\. (school|college|university) → ", text, re.M)
    assert len(examples) == 12
    assert len(re.findall(r'^\{"module":', text, re.M)) == 12


def test_validation_rejects_bad_front_matter() -> None:
    good = {
        "name": "router",
        "version": "1.0.0",
        "model_key": "router",
        "cacheable": True,
        "changelog": [],
    }
    _validate("router", good)
    for bad in (
        {**good, "name": "other"},
        {**good, "version": "1"},
        {**good, "model_key": "nope"},
        {**good, "effort": "high"},  # registry pins router at low
        {k: v for k, v in good.items() if k != "changelog"},
    ):
        with pytest.raises(PromptError):
            _validate("router", bad)


def test_tenant_block_is_deterministic_and_sorted() -> None:
    details = {"office_hours": "x", "address": "45-B Gulberg III", "phone": "+92 42 3575 1100"}
    reordered = {**TENANT, "details": details}
    a, b = render_tenant_block(TENANT), render_tenant_block(reordered)
    assert a == b
    assert "Data version: 7" in a and "Current academic year: 2026-27" in a
    assert a.index("Address:") < a.index("Office hours:") < a.index("Phone:")
    assert not DATE_LIKE.search(a)
    assert tenant_block_version() == "1.0.0"
    with pytest.raises(Exception, match="facts_version"):
        render_tenant_block({k: v for k, v in TENANT.items() if k != "facts_version"})


def test_static_phrases_exist_per_language_and_script() -> None:
    for kind, by_lang in PHRASES.items():
        assert set(by_lang) == {"en", "ur", "roman_ur"}, kind
        assert ARABIC.search(by_lang["ur"]) and not ARABIC.search(by_lang["roman_ur"])
        assert not ARABIC.search(by_lang["en"])
    assert phrase("fallback", "mixed") == PHRASES["fallback"]["roman_ur"]
    assert phrase("fallback", None) == PHRASES["fallback"]["en"]
    assert "office se confirm" in phrase("fallback", "roman_ur")
