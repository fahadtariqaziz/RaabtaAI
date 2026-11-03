"""The tool surface of the agent (PLAN §9.3). Descriptions are written for the model:
what the tool does, when to use it, what it returns."""

import functools

from app.agent.registry import Registry, Tool
from app.agent.tools import booking, facts, fees, knowledge, leads

ADMISSIONS = frozenset({"admissions"})
FEES = frozenset({"fees"})
BOTH = frozenset({"admissions", "fees"})
ALL = frozenset({"all"})


@functools.cache
def build_registry() -> Registry:
    r = Registry()
    r.register(
        Tool(
            "search_knowledge",
            "Search the institution's own documents (prospectus, notices, policies). Use for "
            "descriptive questions: facilities, process, requirements, uniform, timings, hostel. "
            "Returns passages in <source> tags. Numbers in passages are NOT authoritative — use "
            "the get_* fact tools for fees, dates, eligibility and fares.",
            knowledge.SearchInput,
            knowledge.SearchOutput,
            knowledge.search_knowledge,
            modules=ALL,
        )
    )
    r.register(
        Tool(
            "get_fee_table",
            "Approved fee structure (public). Returns fee heads with amount_pkr and frequency for "
            "a class/program (school-wide heads like admission fee are included), or the whole "
            "table. Quote amounts exactly; never add them up.",
            facts.FeeTableInput,
            facts.FactsOutput,
            facts.get_fee_table,
            modules=BOTH,
        )
    )
    r.register(
        Tool(
            "get_programs",
            "Approved list of classes/programs with level, duration, eligibility, seats and "
            "program deadline. Use for 'which programs', eligibility and seats questions.",
            facts.ProgramsInput,
            facts.FactsOutput,
            facts.get_programs,
            modules=ADMISSIONS,
        )
    )
    r.register(
        Tool(
            "get_key_dates",
            "Approved admission calendar: admissions open/close, last date to apply, test and "
            "interview dates, merit lists, session start, vacations. Optional filter word.",
            facts.KeyDatesInput,
            facts.FactsOutput,
            facts.get_key_dates,
            modules=ADMISSIONS,
        )
    )
    r.register(
        Tool(
            "get_scholarships",
            "Approved scholarships/concessions with their criteria and amounts. Never promise "
            "eligibility; quote the criteria.",
            facts.NoInput,
            facts.FactsOutput,
            facts.get_scholarships,
            modules=ADMISSIONS,
        )
    )
    r.register(
        Tool(
            "get_transport_routes",
            "Approved transport (van/bus) routes with areas covered and monthly fare in PKR. "
            "Pass the contact's area to filter.",
            facts.TransportInput,
            facts.FactsOutput,
            facts.get_transport_routes,
            modules=ADMISSIONS,
        )
    )
    r.register(
        Tool(
            "save_lead",
            "Save or update the contact as an admission lead (deduplicated by phone). Use only "
            "details the contact gave. Returns which fields are still missing.",
            leads.SaveLeadInput,
            leads.SaveLeadOutput,
            leads.save_lead,
            side_effect="write",
            modules=ADMISSIONS,
        )
    )
    r.register(
        Tool(
            "get_visit_slots",
            "Open slots for a campus visit, admission test or counselling session in a date "
            "range (default: next two weeks). Returns slot_time strings to use with book_visit.",
            booking.SlotsInput,
            booking.SlotsOutput,
            booking.get_visit_slots,
            modules=ADMISSIONS,
        )
    )
    r.register(
        Tool(
            "book_visit",
            "Book the slot the contact chose. Requires their name and phone. Returns a booking "
            "code to confirm back. Only call after the contact picked a specific slot.",
            booking.BookInput,
            booking.BookOutput,
            booking.book_visit,
            side_effect="write",
            modules=ADMISSIONS,
        )
    )
    r.register(
        Tool(
            "schedule_followup",
            "Schedule the office to follow up on a date the contact agreed to (sent later as a "
            "template message). Use when they want time to decide.",
            leads.FollowupInput,
            leads.FollowupOutput,
            leads.schedule_followup,
            side_effect="write",
            modules=ADMISSIONS,
        )
    )
    r.register(
        Tool(
            "handoff_to_human",
            "Hand the conversation to office staff (they reply in this chat). Use when the "
            "contact asks for a person, complains, disputes a fee, mentions hardship, or you "
            "cannot help after two tries.",
            leads.HandoffInput,
            leads.AckOutput,
            leads.handoff_to_human,
            side_effect="write",
            modules=ALL,
        )
    )
    r.register(
        Tool(
            "set_contact_language",
            "Remember the contact's preferred language when they ask you to switch "
            "(en, ur = Urdu script, roman_ur = Roman Urdu).",
            leads.LanguageInput,
            leads.AckOutput,
            leads.set_contact_language,
            side_effect="write",
            modules=ALL,
        )
    )
    # Fee module (Phase 7): gates are live now, implementations raise "not enabled".
    r.register(
        Tool(
            "verify_parent",
            "Verify a parent before any student-specific fee information: student name + class "
            "or roll number (+ last 4 digits of the registered phone if asked). Max 3 attempts.",
            fees.VerifyInput,
            fees.PendingOutput,
            fees.not_enabled,
            side_effect="gate",
            modules=FEES,
        )
    )
    for name, model, effect, desc in (
        ("get_fee_status", fees.StudentRefInput, "read", "Dues, months and payment channels."),
        (
            "record_payment_promise",
            fees.PromiseInput,
            "write",
            "Record the date the parent promised to pay; schedules a follow-up.",
        ),
        (
            "request_receipt",
            fees.StudentRefInput,
            "state",
            "Ask the parent for a payment receipt photo.",
        ),
        (
            "submit_payment_proof",
            fees.ProofInput,
            "write",
            "Attach a receipt image for staff confirmation.",
        ),
        ("raise_dispute", fees.DisputeInput, "write", "Record a fee dispute and hand off."),
    ):
        r.register(
            Tool(
                name,
                desc + " Verified parents only.",
                model,
                fees.PendingOutput,
                fees.not_enabled,
                permission="verified_parent",
                side_effect=effect,  # type: ignore[arg-type]
                modules=FEES,
            )
        )
    return r
