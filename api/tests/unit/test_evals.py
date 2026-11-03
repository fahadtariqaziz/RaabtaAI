"""Eval harness (step 3.9): graders, metrics/gates, dataset ↔ seed consistency, report format, and
classifier-suite plumbing with a scripted LLM (no spend)."""

from typing import Any

import pytest

from app.agent.schemas import RouteDecision, ToneVerdict
from app.llm.fake import FakeLLM
from evals.graders.agent import (
    Graded,
    date_present,
    fact_present,
    gate,
    grade_admissions,
    grade_guardrail,
    grade_router,
    language_ok,
    load_suite,
    metrics,
    report_md,
    validate_suite,
)
from evals.run_evals import run_router, run_tone, seed_amounts


@pytest.mark.parametrize(
    ("reply", "ok"),
    [
        ("The test is on 13 March 2027.", True),
        ("Test March 13, 2027 ko hai", True),
        ("Saturday 13 Mar, 09:00", True),
        ("ٹیسٹ 13 مارچ 2027 کو ہوگا", True),
        ("Date: 2027-03-13", True),
        ("Test 3 March ko hai", False),
        ("Test 13 May ko hai", False),
    ],
)
def test_date_present(reply: str, ok: bool) -> None:
    assert date_present("2027-03-13", reply) is ok


def test_fact_present_and_language() -> None:
    assert fact_present({"type": "pkr", "value": 12500}, "Fee PKR 12,500 hai")
    assert not fact_present({"type": "pkr", "value": 12500}, "Fee PKR 1,250 hai")
    assert fact_present({"type": "text", "value": ["B-Form", "ب فارم"]}, "ب فارم کی کاپی")
    assert language_ok("roman_ur", "Class 3 ki monthly fee PKR 12,500 hai.")
    assert not language_ok("roman_ur", "کلاس 3 کی فیس ہے")
    assert language_ok("ur", "کلاس 3 کی ماہانہ فیس PKR 12,500 ہے۔")
    assert language_ok("en", "The monthly fee for Class 3 is PKR 12,500.")


def test_grade_router_and_gate() -> None:
    case = {"id": "r1", "expect": {"module": "admissions", "intents_any": ["fee_structure"]}}
    good = {"module": "admissions", "intents": ["fee_structure"], "complexity": "simple"}
    bad = {**good, "module": "fees"}
    results = [grade_router(case, good)] * 19 + [grade_router(case, bad)]
    m = metrics("router", results)
    assert m["accuracy"] == 0.95 and gate("router", m) == []
    m2 = metrics("router", [grade_router(case, bad), grade_router(case, good)])
    assert gate("router", m2) == ["accuracy 0.5 < 0.95"]


def _turn(reply: str, **kw: Any) -> dict[str, Any]:
    return {
        "reply": reply,
        "reply_kind": "answer",
        "tool_calls": [{"name": "get_fee_table", "is_error": False}],
        "citations": [{"title": "Fee structure"}],
        **kw,
    }


def test_grade_admissions_and_metrics() -> None:
    case = load_suite("admissions_school")[0]  # sch-en-fee-class3
    ok = grade_admissions(case, _turn("The monthly fee for Class 3 is PKR 12,500."), None)
    assert ok.passed and ok.checks["facts"] and ok.checks["tools"]
    wrong = grade_admissions(case, _turn("The monthly fee for Class 3 is PKR 13,500."), None)
    assert not wrong.passed and not wrong.checks["facts"]
    no_tool = grade_admissions(case, _turn("PKR 12,500", tool_calls=[]), None)
    assert not no_tool.passed
    judge = {"correctness": 5, "tone": 5, "language_fit": 5, "concision": 4,
             "unsupported_claims": [], "rationale": "ok"}  # fmt: skip
    ok.checks["judge"] = judge
    m = metrics("admissions_school", [ok, wrong])
    assert m["fact_accuracy"] == 0.5 and m["judge_correctness"] == 5
    assert "fact_accuracy 0.5 < 0.98" in gate("admissions_school", m)
    total = next(c for c in load_suite("admissions_school") if c["id"] == "sch-en-no-total")
    forbidden = grade_admissions(
        total, _turn("Class 1: PKR 11,500 monthly; total PKR 56,500"), None
    )
    assert forbidden.checks["forbidden"] == ["56,500"] and not forbidden.passed


def test_grade_guardrails() -> None:
    cases = {c["expect"]["kind"]: c for c in load_suite("guardrails")}
    assert grade_guardrail(cases["injection"], {"reply_kind": "blocked", "reply": "x"}).passed
    assert not grade_guardrail(cases["injection"], {"reply_kind": "answer", "reply": "x"}).passed
    assert grade_guardrail(cases["safe"], {"reply_kind": "answer", "reply": "Jee"}).passed
    assert not grade_guardrail(cases["safe"], {"reply_kind": "blocked", "reply": "x"}).passed
    ident = cases["identity"]
    handoff = {"reply_kind": "handoff", "reply": "office", "tool_calls": []}
    assert grade_guardrail(ident, handoff).passed
    leaked = {"reply_kind": "answer", "reply": "x", "tool_calls": [{"name": "get_fee_status"}]}
    assert not grade_guardrail(ident, leaked).passed


def test_all_datasets_valid_and_consistent_with_seeds() -> None:
    amounts = seed_amounts()
    for suite in ("router", "guardrails", "tone", "admissions_school", "admissions_college",
                  "admissions_university"):  # fmt: skip
        assert validate_suite(suite, amounts) == [], suite
    langs = [c["language"] for c in load_suite("admissions_university")]
    assert langs.count("en") == langs.count("ur") == langs.count("roman_ur") == 20


def test_report_lists_failures() -> None:
    results = [Graded("a", True), Graded("b", False, {"facts": False}, "wrong reply")]
    md = report_md("router", {"accuracy": 0.5}, results, ["accuracy 0.5 < 0.95"])
    assert md.startswith("### Eval `router` — ❌ gate failed")
    assert "`b`" in md and "wrong reply" in md and "1 failing cases" in md


async def test_classifier_suites_plumbing_with_fake_llm() -> None:
    cases = load_suite("router")[:5]

    def route_for(request: dict[str, Any]) -> RouteDecision:
        msg = request["messages"][0]["content"].split("<new_message>\n")[1].split("\n</new")[0]
        exp = next(c for c in cases if c["message"] == msg)["expect"]
        return RouteDecision(
            module=exp["module"],
            intents=[exp["intents_any"][0]],
            complexity=exp.get("complexity", "simple"),
            needs_identity=False,
            skills=["nope"],
            search_queries=[],
            confidence=0.9,
        )

    results = await run_router(FakeLLM({"router": route_for}), cases)
    assert [r.passed for r in results] == [True] * 5
    tone_cases = [c for c in load_suite("tone") if c["id"] in ("t01-good", "t21-bad")]
    verdicts = [
        ToneVerdict(ok=True, score=5, issues=[]),
        ToneVerdict(ok=False, score=1, issues=["threat"]),
    ]
    tone = await run_tone(FakeLLM({"tone_check": verdicts}), tone_cases)
    assert [r.passed for r in tone] == [True, True]
    assert metrics("tone", tone)["good_mean"] == 5
