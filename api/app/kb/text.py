"""Text utilities for ingestion and search (step 2.3): normalization (`text_norm`), token estimate,
language/script tagging and the prompt-injection pre-filter (PLAN §11 rule 10).

`normalize()` runs on both chunk text and queries, so spelling variants meet in the middle:
lower-case, Latin accents stripped (unaccent-like), Urdu diacritics removed and Arabic letter
variants folded to Urdu forms, thousands separators dropped, and common Roman-Urdu spellings
mapped to one canonical form ("dakhila"/"dakhla" → "dakhla")."""

import math
import re
import unicodedata

# Arabic → Urdu letter variants (same letter, different code points in the wild).
_URDU_FOLD = str.maketrans(
    {
        "ي": "ی",  # ي → ی
        "ى": "ی",  # ى → ی
        "ك": "ک",  # ك → ک
        "ه": "ہ",  # ه → ہ
        "ة": "ۃ",  # ة → ۃ
        "ۀ": "ہ",  # ۀ → ہ
        "ـ": None,  # tatweel
        "‌": None,  # ZWNJ
        "‍": None,  # ZWJ
        "۔": ".",  # Urdu full stop
        "،": ",",  # Arabic comma
        "؟": "?",  # Arabic question mark
    }
)
_URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# Roman-Urdu spelling variants → canonical token. Keep small and high-precision; broader
# meaning-level expansion (Roman Urdu → English) lives in seeds/ru_synonyms.csv (query side only).
ROMAN_URDU_CANON: dict[str, str] = {
    **dict.fromkeys(["fees", "fess", "fis", "feez", "fise"], "fee"),
    **dict.fromkeys(["dakhila", "dakhlay", "daakhla", "dakhle", "dakhley", "dakhlah"], "dakhla"),
    **dict.fromkeys(["admisson", "admision", "admissions", "addmission", "admition"], "admission"),
    **dict.fromkeys(["kitni", "kitne", "kitny", "kitna", "kitnay", "kitnee"], "kitna"),
    **dict.fromkeys(["hy", "he", "hay", "hain", "hein", "hai"], "hai"),
    **dict.fromkeys(["mein", "main", "mai", "mey", "men"], "mein"),
    **dict.fromkeys(["kya", "kia", "kiya", "kyaa"], "kya"),
    **dict.fromkeys(["nahi", "nahin", "nai", "nhi", "nahee"], "nahi"),
    **dict.fromkeys(["skool", "scool", "schol"], "school"),
    **dict.fromkeys(["vaan", "wan", "vans", "van"], "van"),
    **dict.fromkeys(["timing", "timings", "time", "timmings", "taim", "waqt"], "timing"),
    **dict.fromkeys(["scholarships", "scolarship", "scholership"], "scholarship"),
    **dict.fromkeys(["hostal", "hostle", "hostels"], "hostel"),
    **dict.fromkeys(["uniforms", "unifarm", "yuniform"], "uniform"),
    **dict.fromkeys(["semister", "semestar", "simester", "semesters"], "semester"),
    **dict.fromkeys(["mahina", "mahine", "mahiney", "mahinay", "maheena"], "mahina"),
    **dict.fromkeys(["talib", "talba"], "talib"),
    **dict.fromkeys(["chutti", "chuti", "chuttiyan", "chutiyan"], "chutti"),
    **dict.fromkeys(["imtihan", "imtehan", "imthan", "imtihaan"], "imtihan"),
    **dict.fromkeys(["test", "tests", "taist"], "test"),
}

_WORD = re.compile(r"\w+", re.UNICODE)
_THOUSANDS = re.compile(r"(?<=\d)[,٬](?=\d{2,3}\b)")


def _strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    kept = "".join(c for c in decomposed if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", kept)


def normalize(text: str) -> str:
    """Canonical lower-case form used for FTS (`tsv`) and trigram matching."""
    out = unicodedata.normalize("NFKC", text).translate(_URDU_FOLD).translate(_URDU_DIGITS)
    out = _strip_marks(out.lower())
    out = _THOUSANDS.sub("", out)
    return _WORD.sub(lambda m: ROMAN_URDU_CANON.get(m.group(0), m.group(0)), out)


def words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (no tokenizer dependency): Latin ≈ 4 chars/token, Urdu script ≈ 2.5."""
    arabic = len(_ARABIC.findall(text))
    latin = len(_LATIN.findall(text))
    other = max(len(text) - arabic - latin, 0)
    return max(1, math.ceil(latin / 4 + arabic / 2.5 + other / 3))


# Frequent Roman-Urdu function words (rare in English text).
_RU_MARKERS_TEXT = (
    "hai kya ka ki ke ko mein se aur nahi kab kahan kaise kitna bhi hum ap aap apko apka "
    "batain bataen bata chahiye wala wali walay hoga hogi tha thi raha rahi kar karna karein "
    "mujhe mera meri humara bacha bachay beta beti dakhla"
)
_RU_MARKERS = frozenset(_RU_MARKERS_TEXT.split())


def detect_lang(text: str) -> str:
    """'ur' (Urdu script), 'roman_ur', 'en' or 'mixed' — script detection + marker words.
    No LLM at ingestion (step 2.3.3)."""
    arabic = len(_ARABIC.findall(text))
    latin = len(_LATIN.findall(text))
    if arabic + latin == 0:
        return "en"
    share = arabic / (arabic + latin)
    if share >= 0.7:
        return "ur"
    if share >= 0.2:
        return "mixed"
    tokens = words(text)
    if not tokens:
        return "en"
    ru = sum(t in _RU_MARKERS for t in tokens) / len(tokens)
    return "roman_ur" if ru >= 0.2 else "en"


# Instructions hidden in uploaded documents (PLAN §10/§11): flagged at ingestion, excluded from
# retrieval by default, visible to admins in the chunk view.
_INJECTION = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|all|any)\b.{0,40}"
        r"\b(instructions?|rules?|prompts?|directions?)",
        r"\bsystem\s*prompt\b",
        r"\byou\s+are\s+now\b",
        r"\bact\s+as\s+(an?\s+)?(different|new|unrestricted)\b",
        r"\bnew\s+instructions?\s*:",
        r"\bdeveloper\s+mode\b",
        r"<\|?(im_start|im_end|system|endoftext)\|?>",
        r"^\s*(system|assistant)\s*:",
        r"\b(reveal|print|show)\b.{0,30}\b(api\s*key|password|secret|instructions)\b",
        r"(پچھلی|سابقہ)\s+(تمام\s+)?(ہدایات|ہدایت)",
        r"\b(pichli|pehli)\s+(sari\s+)?hidayat\b",
    )
]


def looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION)
