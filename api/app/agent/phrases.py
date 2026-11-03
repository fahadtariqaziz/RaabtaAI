"""Static replies per language (PLAN §10 G1/G2/G7/G13). Deterministic — never LLM-generated.
Keys: `en`, `ur` (Urdu script), `roman_ur`; `mixed` falls back to Roman Urdu."""

PHRASES: dict[str, dict[str, str]] = {
    "fallback": {
        "en": "I don't have confirmed information on that yet — I'll check with the office and "
        "get back to you.",
        "roman_ur": "Is baare mein abhi confirm maloomat mere paas nahi hai — office se confirm "
        "karke aap ko batate hain.",
        "ur": "اس بارے میں ابھی تصدیق شدہ معلومات میرے پاس نہیں ہیں — دفتر سے تصدیق کر کے آپ کو "
        "بتاتے ہیں۔",
    },
    "blocked": {
        "en": "I can only help with admissions and fee questions for this institution. How can I "
        "help you with those?",
        "roman_ur": "Main sirf is idaray ke admissions aur fee ke sawalat mein madad kar sakta "
        "hoon. Bataiye, kis cheez mein madad karun?",
        "ur": "میں صرف اس ادارے کے داخلوں اور فیس سے متعلق سوالات میں مدد کر سکتا ہوں۔ بتائیے، کس "
        "چیز میں مدد کروں؟",
    },
    "off_topic": {
        "en": "I'm the institution's assistant, so I can help with admissions, fees, visits and "
        "transport. What would you like to know?",
        "roman_ur": "Main idaray ka assistant hoon — admissions, fee, campus visit aur transport "
        "ke baare mein madad kar sakta hoon. Aap kya jaanna chahenge?",
        "ur": "میں ادارے کا اسسٹنٹ ہوں — داخلے، فیس، کیمپس وزٹ اور ٹرانسپورٹ کے بارے میں مدد کر "
        "سکتا ہوں۔ آپ کیا جاننا چاہیں گے؟",
    },
    "handoff": {
        "en": "I've passed this to a colleague at the office — they will reply to you here soon.",
        "roman_ur": "Maine aap ki baat office ke ek sathi tak pohncha di hai — woh jald yahin "
        "jawab denge.",
        "ur": "میں نے آپ کی بات دفتر کے ایک ساتھی تک پہنچا دی ہے — وہ جلد یہیں جواب دیں گے۔",
    },
    "rate_limited": {
        "en": "You've sent a lot of messages in a short time. Please wait a few minutes and try "
        "again.",
        "roman_ur": "Aap ne kam waqt mein bohat se messages bheje hain. Baraye meharbani kuch "
        "minute baad dobara koshish karein.",
        "ur": "آپ نے کم وقت میں بہت سے پیغامات بھیجے ہیں۔ براہ کرم چند منٹ بعد دوبارہ کوشش کریں۔",
    },
    "daily_cap": {
        "en": "We've reached today's limit for automatic replies in this chat. A colleague from "
        "the office will continue with you.",
        "roman_ur": "Is chat mein aaj ke automatic jawabat ki had poori ho gayi hai. Office ka ek "
        "sathi aap se baat aage barhayega.",
        "ur": "اس چیٹ میں آج کے خودکار جوابات کی حد پوری ہو گئی ہے۔ دفتر کا ایک ساتھی آپ سے بات "
        "آگے بڑھائے گا۔",
    },
    "opted_out": {
        "en": "You won't receive further messages from us. Send START any time to resume.",
        "roman_ur": "Aap ko ab hamari taraf se mazeed messages nahi aayenge. Dobara shuru karne ke "
        "liye kabhi bhi START bhejein.",
        "ur": "آپ کو اب ہماری طرف سے مزید پیغامات نہیں آئیں گے۔ دوبارہ شروع کرنے کے لیے کبھی بھی "
        "START بھیجیں۔",
    },
    "error": {
        "en": "Sorry, something went wrong on our side. Please try again in a moment, or a "
        "colleague from the office will get back to you.",
        "roman_ur": "Maazrat, hamari taraf se koi masla aa gaya. Thori dair baad dobara koshish "
        "karein, ya office ka sathi aap se rabta karega.",
        "ur": "معذرت، ہماری طرف سے کوئی مسئلہ آ گیا۔ تھوڑی دیر بعد دوبارہ کوشش کریں، یا دفتر کا "
        "ساتھی آپ سے رابطہ کرے گا۔",
    },
}


def lang_key(language: str | None) -> str:
    return language if language in ("en", "ur", "roman_ur") else "roman_ur" if language else "en"


def phrase(kind: str, language: str | None) -> str:
    return PHRASES[kind][lang_key(language)]
