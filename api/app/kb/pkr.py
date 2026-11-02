"""Deterministic money/frequency normalization (CLAUDE.md: never LLM arithmetic).

parse_pkr("Rs. 12,500/-") == 12500 · parse_pkr("PKR 1.45 lac") == 145000 ·
parse_pkr("1,45,000") == 145000 · parse_pkr("15k") == 15000 · parse_pkr("Free") is None
"""

import re
from decimal import Decimal, InvalidOperation

_MULT = {
    "k": 1_000,
    "thousand": 1_000,
    "hazar": 1_000,
    "hazaar": 1_000,
    "ہزار": 1_000,
    "lac": 100_000,
    "lakh": 100_000,
    "lacs": 100_000,
    "lakhs": 100_000,
    "لاکھ": 100_000,
    "m": 1_000_000,
    "million": 1_000_000,
}
_NUM = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|hazaa?r|ہزار|lacs?|lakhs?|لاکھ|million|m)?\b",
    re.IGNORECASE,
)


def parse_pkr(value: object) -> int | None:
    """Whole rupees from a cell/LLM string; None if no unambiguous single amount."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return round(value) if value >= 0 else None
    text = str(value).strip().lower().replace("/-", "")
    matches = [m for m in _NUM.finditer(text) if m.group(1).strip(",")]
    if len(matches) != 1:
        return None  # "10,000–15,000" or no number → not a single amount
    number, unit = matches[0].group(1).replace(",", ""), matches[0].group(2)
    try:
        amount = Decimal(number)
    except InvalidOperation:
        return None
    if unit:
        amount *= _MULT[unit.lower()]
    return int(amount.to_integral_value())


_FREQ = [
    (re.compile(r"one[\s-]?time|once|admission|non[\s-]?recurring|ek\s*dafa|refundab"), "one_time"),
    (re.compile(r"month|mahana|ماہانہ|per\s*mo\b|/\s*mo\b|p\.?m\.?\b"), "monthly"),
    (re.compile(r"quarter|teen\s*mah"), "quarterly"),
    (re.compile(r"semester|sem\b|term"), "per_semester"),
    (re.compile(r"annual|year|yearly|salana|سالانہ|p\.?a\.?\b"), "annual"),
]


def parse_frequency(value: object, default: str | None = None) -> str | None:
    if value is None:
        return default
    text = str(value).strip().lower().replace("_", " ")
    for pattern, freq in _FREQ:
        if pattern.search(text):
            return freq
    return default
