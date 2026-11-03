"""Step 3.9 — agent eval suites end-to-end through the real graph on the seeded test DB with a
scripted LLM (plumbing only; real quality = live run). Needs `app.cli seed` + `ingest-seeds` on
the test DB first (scripts/verify/p3_s9.sh does that)."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.agent.schemas import CheckResult, GuardVerdict, RouteDecision, Summary
from app.core.config import Settings
from app.db.session import make_sessionmaker
from app.kb.embeddings import make_provider
from app.llm.fake import FakeLLM, text_reply, tool_call
from evals.graders.agent import JudgeVerdict, load_suite, metrics
from evals.run_evals import institution_ids, run_agent_cases

pytestmark = pytest.mark.integration

SUMMARY = Summary.model_validate(
    {
        "facts": [],
        "open_questions": [],
        "lead": {"student_name": None, "guardian_name": None, "phone": None, "interest": None},
        "profile": {
            "guardian_name": None,
            "student_name": None,
            "student_class": None,
            "preferred_language": None,
            "phone": None,
        },
        "stage": "exploring",
        "goal_status": "answered",
        "verified": False,
        "last_promise": None,
    }
)


async def test_admissions_and_guardrails_suites_run_through_the_graph(
    it_settings: Settings,
) -> None:
    engine = create_async_engine(it_settings.database_url, poolclass=NullPool)
    sm = make_sessionmaker(engine)
    try:
        if not await institution_ids(sm, {"abc-grammar-school"}):
            pytest.skip("demo institutions not seeded in the test DB")
        case = next(c for c in load_suite("admissions_school") if c["id"] == "sch-en-fee-class3")
        llm = FakeLLM(
            {
                "guard_in": GuardVerdict(
                    language="en",
                    injection=False,
                    abuse=False,
                    pii_request=False,
                    off_topic=False,
                    reason="ok",
                ),
                "router": RouteDecision(
                    module="admissions",
                    intents=["fee_structure"],
                    complexity="simple",
                    needs_identity=False,
                    skills=[],
                    search_queries=[],
                    confidence=0.9,
                ),
                "agent_simple": [
                    tool_call(
                        "get_fee_table", {"program_or_class": "Class 3", "academic_year": None}
                    ),
                    text_reply("The monthly tuition fee for Class 3 is PKR 12,500."),
                ],
                "answer_check": CheckResult(
                    claims=[],
                    language_ok=True,
                    identity_leak=False,
                    ok=True,
                    unsupported_claims=[],
                    fixes=[],
                ),
                "summarizer": SUMMARY,
                "eval_judge": JudgeVerdict(
                    correctness=5,
                    tone=5,
                    language_fit=5,
                    concision=5,
                    unsupported_claims=[],
                    rationale="exact",
                ),
            }
        )
        results = await run_agent_cases(
            "admissions_school",
            [case],
            llm,
            sm,
            embedder=make_provider(it_settings),
            judge=llm,
            stamp="t",
        )
        assert results[0].passed, results[0].checks
        assert results[0].checks["cited"] and results[0].checks["judge"]["correctness"] == 5
        assert metrics("admissions_school", results)["fact_accuracy"] == 1.0

        injection = load_suite("guardrails")[0]  # pre-filter blocks without any LLM call
        guarded = await run_agent_cases(
            "guardrails", [injection], FakeLLM({}), sm, embedder=None, judge=None, stamp="t"
        )
        assert guarded[0].passed and guarded[0].checks["blocked"]
    finally:
        await engine.dispose()
