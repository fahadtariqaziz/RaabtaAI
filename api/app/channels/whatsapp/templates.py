"""Template rendering, Meta submission payloads and the default template set (step 6.5).

Bodies use named placeholders (`{{name}}`); Meta wants positional ones (`{{1}}`), numbered in the
order of `variables`. Rendering is deterministic code — reminders are never LLM-generated (§6.2).
Roman Urdu has no Meta language code: it is submitted as `en` under the name `<name>_ru`."""

import re
from dataclasses import dataclass
from typing import Any

from app.models.templates import Template

PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]{0,31})\s*\}\}")
META_LANGUAGE = {"en": "en", "ur": "ur", "roman_ur": "en"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,120}$")
BODY_LIMIT = 1024


class TemplateError(ValueError):
    pass


def extract_variables(body: str) -> list[str]:
    seen: list[str] = []
    for name in PLACEHOLDER.findall(body):
        if name not in seen:
            seen.append(name)
    return seen


def validate(name: str, body: str) -> list[str]:
    """Return the body's variables or raise TemplateError (Meta's basic rules)."""
    if not NAME_RE.fullmatch(name):
        raise TemplateError("name: lowercase letters, digits and underscores only")
    if not body.strip() or len(body) > BODY_LIMIT:
        raise TemplateError(f"body must be 1–{BODY_LIMIT} characters")
    stripped = body.strip()
    if stripped.startswith("{{") or stripped.endswith("}}"):  # Meta rejects these
        raise TemplateError("body must not start or end with a variable")
    if "{{" in PLACEHOLDER.sub("", body):
        raise TemplateError("placeholders look like {{name}} (lowercase, digits, underscores)")
    return extract_variables(body)


def meta_name(tpl: Template) -> str:
    return f"{tpl.name}_ru" if tpl.language == "roman_ur" else tpl.name


def meta_language(language: str) -> str:
    return META_LANGUAGE[language]


def positional_body(body: str, variables: list[str]) -> str:
    index = {v: i + 1 for i, v in enumerate(variables)}
    return PLACEHOLDER.sub(lambda m: f"{{{{{index[m.group(1)]}}}}}", body)


def render(tpl: Template, values: dict[str, Any]) -> tuple[str, list[str]]:
    """→ (text as the parent sees it, positional parameters for Meta). Missing value → error."""
    missing = [v for v in tpl.variables if values.get(v) in (None, "")]
    if missing:
        raise TemplateError(f"missing template values: {', '.join(missing)}")
    params = [" ".join(str(values[v]).split())[:200] for v in tpl.variables]
    lookup = dict(zip(tpl.variables, params, strict=True))
    text = PLACEHOLDER.sub(lambda m: lookup.get(m.group(1), m.group(0)), tpl.body)
    return text, params


def submit_payload(tpl: Template) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "BODY", "text": positional_body(tpl.body, tpl.variables)}
    if tpl.variables:
        examples = list(tpl.examples or [])
        examples += [f"sample {v}" for v in tpl.variables[len(examples) :]]
        body["example"] = {"body_text": [examples[: len(tpl.variables)]]}
    return {
        "name": meta_name(tpl),
        "language": meta_language(tpl.language),
        "category": tpl.category.upper(),
        "components": [body],
    }


@dataclass(frozen=True)
class DefaultTemplate:
    name: str
    examples: dict[str, str]
    bodies: dict[str, str]  # language → body
    category: str = "utility"


_EX = {
    "name": "Ayesha Khan",
    "institution": "ABC Grammar School",
    "student": "Ali",
    "date": "Sat 14 Nov, 10:00 AM",
    "place": "Main campus, Gulberg",
    "code": "V7K2Q9",
    "amount": "Rs 12,500",
    "due_date": "10 Nov 2026",
    "month": "November 2026",
    "promised_date": "12 Nov 2026",
    "conversations": "42",
    "leads": "9",
    "bookings": "4",
    "flagged": "2",
    "day": "Wed 4 Nov",
}


def _ex(*keys: str) -> dict[str, str]:
    return {k: _EX[k] for k in keys}


# Wording is reviewed by the institution before submission (👤 step 6.5). Respectful, short,
# no threats or shaming in fee reminders (G5); the institution's name always appears.
DEFAULT_TEMPLATES: tuple[DefaultTemplate, ...] = (
    DefaultTemplate(
        "admission_followup_1",
        _ex("name", "institution"),
        {
            "en": "Assalam o Alaikum {{name}}, thank you for your interest in {{institution}}. "
            "Do you have any other questions about admissions? Just reply here and we will help.",
            "roman_ur": "Assalam o Alaikum {{name}}, {{institution}} mein dilchaspi ka shukriya. "
            "Kya admissions ke baare mein aap ka koi aur sawal hai? Yahin reply karein, hum madad "
            "karenge.",
            "ur": "السلام علیکم {{name}}، {{institution}} میں دلچسپی کا شکریہ۔ کیا داخلوں کے بارے "
            "میں آپ کا کوئی اور سوال ہے؟ یہیں جواب دیں، ہم مدد کریں گے۔",
        },
    ),
    DefaultTemplate(
        "admission_followup_2",
        _ex("name", "institution"),
        {
            "en": "Assalam o Alaikum {{name}}, a gentle reminder from {{institution}}: seats for "
            "the new session are filling up. Would you like to book a campus visit? Reply YES and "
            "we will share the available times.",
            "roman_ur": "Assalam o Alaikum {{name}}, {{institution}} ki taraf se yaad dehani: naye "
            "session ki seats bhar rahi hain. Kya aap campus visit book karna chahenge? YES reply "
            "karein, hum available waqt bata denge.",
            "ur": "السلام علیکم {{name}}، {{institution}} کی طرف سے یاد دہانی: نئے سیشن کی نشستیں "
            "بھر رہی ہیں۔ کیا آپ کیمپس وزٹ بک کرنا چاہیں گے؟ YES لکھ کر جواب دیں، ہم دستیاب اوقات "
            "بتا دیں گے۔",
        },
    ),
    DefaultTemplate(
        "visit_confirmation",
        _ex("name", "institution", "date", "place", "code"),
        {
            "en": "Dear {{name}}, your visit to {{institution}} is confirmed for {{date}} at "
            "{{place}}. Booking code: {{code}}. Reply here if you need to change it.",
            "roman_ur": "Mohtaram {{name}}, {{institution}} ka visit {{date}} ko {{place}} par "
            "confirm ho gaya hai. Booking code: {{code}}. Tabdeeli ke liye yahin reply karein.",
            "ur": "محترم {{name}}، {{institution}} کا وزٹ {{date}} کو {{place}} پر کنفرم ہو گیا "
            "ہے۔ بکنگ کوڈ: {{code}}۔ تبدیلی کے لیے یہیں جواب دیں۔",
        },
    ),
    DefaultTemplate(
        "visit_reminder",
        _ex("name", "institution", "date", "place", "code"),
        {
            "en": "Reminder: {{name}}, your visit to {{institution}} is tomorrow, {{date}} at "
            "{{place}} (code {{code}}). We look forward to meeting you.",
            "roman_ur": "Yaad dehani: {{name}}, {{institution}} ka visit kal {{date}} ko {{place}} "
            "par hai (code {{code}}). Aap se mil kar khushi hogi.",
            "ur": "یاد دہانی: {{name}}، {{institution}} کا وزٹ کل {{date}} کو {{place}} پر ہے (کوڈ "
            "{{code}})۔ آپ سے مل کر خوشی ہوگی۔",
        },
    ),
    DefaultTemplate(
        "fee_reminder_1",
        _ex("name", "student", "amount", "month", "due_date", "institution"),
        {
            "en": "Assalam o Alaikum {{name}}, this is a friendly reminder that {{student}}'s fee "
            "of {{amount}} for {{month}} is due on {{due_date}}. If already paid, please ignore "
            "this message. — {{institution}}.",
            "roman_ur": "Assalam o Alaikum {{name}}, yaad dehani ke liye: {{student}} ki {{month}} "
            "ki fee {{amount}} ki aakhri tareekh {{due_date}} hai. Agar ada kar chuke hain to is "
            "message ko nazar andaz karein. — {{institution}}.",
            "ur": "السلام علیکم {{name}}، یاد دہانی کے لیے: {{student}} کی {{month}} کی فیس "
            "{{amount}} کی آخری تاریخ {{due_date}} ہے۔ اگر ادا کر چکے ہیں تو اس پیغام کو نظر انداز "
            "کریں۔ — {{institution}}.",
        },
    ),
    DefaultTemplate(
        "fee_reminder_2",
        _ex("name", "student", "amount", "due_date", "institution"),
        {
            "en": "Dear {{name}}, {{student}}'s fee of {{amount}} was due on {{due_date}} and is "
            "still showing as unpaid. If you have paid, you can send a photo of the receipt "
            "here. — {{institution}}.",
            "roman_ur": "Mohtaram {{name}}, {{student}} ki fee {{amount}} ki tareekh {{due_date}} "
            "thi aur abhi tak unpaid show ho rahi hai. Agar ada kar di hai to receipt ki tasveer "
            "yahin bhej dein. — {{institution}}.",
            "ur": "محترم {{name}}، {{student}} کی فیس {{amount}} کی تاریخ {{due_date}} تھی اور "
            "ابھی تک ادا شدہ ظاہر نہیں ہو رہی۔ اگر ادا کر دی ہے تو رسید کی تصویر یہیں بھیج دیں۔ — "
            "{{institution}}.",
        },
    ),
    DefaultTemplate(
        "fee_reminder_3",
        _ex("name", "student", "amount", "institution"),
        {
            "en": "Dear {{name}}, {{student}}'s outstanding fee is {{amount}}. If paying in full "
            "is difficult right now, reply here and we can discuss a convenient date. — "
            "{{institution}}.",
            "roman_ur": "Mohtaram {{name}}, {{student}} ki baqaya fee {{amount}} hai. Agar abhi "
            "poori ada karna mushkil ho to yahin reply karein, hum munasib tareekh tay kar sakte "
            "hain. — {{institution}}.",
            "ur": "محترم {{name}}، {{student}} کی بقایا فیس {{amount}} ہے۔ اگر ابھی پوری ادا کرنا "
            "مشکل ہو تو یہیں جواب دیں، ہم مناسب تاریخ طے کر سکتے ہیں۔ — {{institution}}.",
        },
    ),
    DefaultTemplate(
        "fee_reminder_4",
        _ex("name", "student", "amount", "institution"),
        {
            "en": "Dear {{name}}, {{student}}'s fee of {{amount}} is still pending. Our accounts "
            "office would be glad to help — please reply here or visit the office at your "
            "convenience. — {{institution}}.",
            "roman_ur": "Mohtaram {{name}}, {{student}} ki fee {{amount}} abhi baqi hai. Accounts "
            "office aap ki madad ke liye haazir hai — yahin reply karein ya apni suhoolat se "
            "office tashreef layein. — {{institution}}.",
            "ur": "محترم {{name}}، {{student}} کی فیس {{amount}} ابھی باقی ہے۔ اکاؤنٹس آفس آپ کی "
            "مدد کے لیے حاضر ہے — یہیں جواب دیں یا اپنی سہولت سے دفتر تشریف لائیں۔ — "
            "{{institution}}.",
        },
    ),
    DefaultTemplate(
        "promise_followup",
        _ex("name", "student", "promised_date", "institution"),
        {
            "en": "Assalam o Alaikum {{name}}, you mentioned that {{student}}'s fee would be paid "
            "by {{promised_date}}. If it has been paid, please share the receipt here. Thank you. "
            "— {{institution}}.",
            "roman_ur": "Assalam o Alaikum {{name}}, aap ne bataya tha ke {{student}} ki fee "
            "{{promised_date}} tak ada ho jayegi. Agar ada ho gayi hai to receipt yahin share kar "
            "dein. Shukriya. — {{institution}}.",
            "ur": "السلام علیکم {{name}}، آپ نے بتایا تھا کہ {{student}} کی فیس {{promised_date}} "
            "تک ادا ہو جائے گی۔ اگر ادا ہو گئی ہے تو رسید یہیں بھیج دیں۔ شکریہ۔ — {{institution}}.",
        },
    ),
    DefaultTemplate(
        "receipt_received",
        _ex("name", "student", "institution"),
        {
            "en": "Thank you {{name}}. We have received the payment receipt for {{student}}; our "
            "accounts office will confirm it shortly. — {{institution}}.",
            "roman_ur": "Shukriya {{name}}. {{student}} ki fee ki receipt mil gayi hai; accounts "
            "office jald confirm kar dega. — {{institution}}.",
            "ur": "شکریہ {{name}}۔ {{student}} کی فیس کی رسید مل گئی ہے؛ اکاؤنٹس آفس جلد تصدیق کر "
            "دے گا۔ — {{institution}}.",
        },
    ),
    DefaultTemplate(
        "daily_summary",
        _ex("institution", "day", "conversations", "leads", "bookings", "flagged"),
        {
            "en": "RaabtaAI summary for {{institution}}, {{day}}: {{conversations}} "
            "conversations, {{leads}} new leads, {{bookings}} visits booked, {{flagged}} need "
            "attention. Details are in the admin panel.",
            "roman_ur": "RaabtaAI khulasa, {{institution}} — {{day}}: {{conversations}} "
            "conversations, {{leads}} naye leads, {{bookings}} visits book, {{flagged}} par "
            "tawajjo darkar. Tafseel admin panel mein hai.",
            "ur": "RaabtaAI خلاصہ، {{institution}} — {{day}}: {{conversations}} گفتگوئیں، "
            "{{leads}} نئے لیڈز، {{bookings}} وزٹ بک، {{flagged}} پر توجہ درکار۔ تفصیل ایڈمن پینل "
            "میں ہے۔",
        },
    ),
)


def default_rows() -> list[dict[str, Any]]:
    rows = []
    for d in DEFAULT_TEMPLATES:
        for lang, body in d.bodies.items():
            variables = extract_variables(body)
            rows.append(
                {
                    "name": d.name,
                    "language": lang,
                    "category": d.category,
                    "body": body,
                    "variables": variables,
                    "examples": [d.examples[v] for v in variables],
                }
            )
    return rows
