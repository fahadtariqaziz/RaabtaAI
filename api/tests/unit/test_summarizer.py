"""Summarizer & contact memory (step 3.8): goal tracking, summarizer input, LTM writes (profile,
language, name, lead only from a phone the contact typed)."""

import uuid
from typing import Any

from app.agent.memory import apply_summary, goal_from_events, merge_goal, summarizer_input
from app.agent.schemas import Summary
from app.models.conversations import Contact, Conversation, Lead


def summary(phone: str | None = None) -> Summary:
    return Summary.model_validate(
        {
            "facts": ["Interested in Class 3"],
            "open_questions": ["transport from DHA"],
            "lead": {
                "student_name": "Hamza",
                "guardian_name": "Ayesha Malik",
                "phone": phone,
                "interest": "Class 3",
            },
            "profile": {
                "guardian_name": "Ayesha Malik",
                "student_name": "Hamza",
                "student_class": "Class 3",
                "preferred_language": "roman_ur",
                "phone": None,
            },
            "stage": "interested",
            "goal_status": "lead_captured",
            "verified": False,
            "last_promise": None,
        }
    )


def test_goal_status_only_moves_up() -> None:
    assert merge_goal(None) == "open"
    assert merge_goal("booked", "answered") == "booked"
    assert merge_goal("answered", "lead_captured", None) == "lead_captured"
    assert goal_from_events([], answered=True) == "answered"
    assert goal_from_events([{"type": "lead_saved", "has_phone": False}], answered=False) == "open"
    events: list[dict[str, Any]] = [
        {"type": "lead_saved", "has_phone": True},
        {"type": "booked", "code": "X"},
    ]
    assert goal_from_events(events, answered=True) == "booked"
    assert goal_from_events([{"type": "handoff"}], answered=False) == "handed_off"


def test_summarizer_input_shape() -> None:
    text = summarizer_input(
        previous={"facts": ["a"]},
        verified=False,
        user_text="Class 3 fee?",
        reply="PKR 12,500",
        tools_line="[looked up: fee table (Class 3)]",
        events=[{"type": "booked", "code": "K7M2QX"}],
        staff_notes=["Principal will call"],
    )
    assert text.startswith('<previous_summary>\n{"facts": ["a"]}\n</previous_summary>')
    assert "<verified>no</verified>" in text and "<staff_notes>\nPrincipal will call" in text
    assert "Contact: Class 3 fee?\n[looked up: fee table (Class 3)]\nAssistant: PKR 12,500" in text
    assert 'Actions: {"code": "K7M2QX", "type": "booked"}' in text


class FakeSession:
    def __init__(self, contact: Contact, conv: Conversation) -> None:
        self.objs: dict[Any, Any] = {(Contact, contact.id): contact, (Conversation, conv.id): conv}
        self.added: list[Any] = []

    async def get(self, model: Any, key: Any) -> Any:
        return self.objs.get((model, key))

    async def scalar(self, _stmt: Any) -> Any:
        return None

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self) -> None:
        return None


async def _apply(phone: str | None, contact_text: str) -> tuple[Contact, Conversation, FakeSession]:
    contact = Contact(id=uuid.uuid4(), profile={"stage": "new"}, name=None)
    conv = Conversation(id=uuid.uuid4(), contact_id=contact.id, channel="widget", thread_id="t")
    session = FakeSession(contact, conv)
    await apply_summary(
        session,  # type: ignore[arg-type]
        contact_id=contact.id,
        conversation_id=conv.id,
        channel="widget",
        summary=summary(phone),
        goal_status="answered",
        contact_text=contact_text,
    )
    return contact, conv, session


async def test_apply_summary_writes_profile_and_lead_only_for_typed_phone() -> None:
    contact, conv, session = await _apply(None, "")
    assert conv.summary and conv.summary["goal_status"] == "answered"
    assert contact.profile == {
        "stage": "interested",
        "guardian_name": "Ayesha Malik",
        "student_name": "Hamza",
        "student_class": "Class 3",
    }
    assert contact.preferred_language == "roman_ur" and contact.name == "Ayesha Malik"
    assert session.added == []

    _, _, hallucinated = await _apply("0300-1234567", "mera beta class 3 mein jayega")
    assert hallucinated.added == []  # phone never typed by the contact → no lead

    contact, conv, typed = await _apply("0300-1234567", "mera number 0300 1234567 hai")
    leads = [o for o in typed.added if isinstance(o, Lead)]
    assert len(leads) == 1 and leads[0].phone == "+923001234567"
    assert leads[0].student_name == "Hamza" and conv.lead_id == leads[0].id
    assert contact.phone == "+923001234567"
