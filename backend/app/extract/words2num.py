"""Amount in words (Indian system: crore, lakh, thousand, hundred, plus paise) → Decimal."""

from __future__ import annotations

import re
from decimal import Decimal

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
_SCALES = {"crore": 10_000_000, "crores": 10_000_000, "lakh": 100_000, "lakhs": 100_000,
           "lac": 100_000, "lacs": 100_000, "thousand": 1000, "million": 1_000_000}  # fmt: skip
_NOISE = {"rupees", "rupee", "rs", "inr", "only", "and", "indian", "the", "sum", "of"}


def _words_to_int(words: list[str]) -> int | None:
    total = 0
    current = 0
    seen = False
    for w in words:
        if w in _NOISE:
            continue
        if w in _UNITS:
            current += _UNITS[w]
            seen = True
        elif w == "hundred":
            current = (current or 1) * 100
            seen = True
        elif w in _SCALES:
            total += (current or 1) * _SCALES[w]
            current = 0
            seen = True
        else:
            return None
    return total + current if seen else None


def words_to_amount(text: str | None) -> Decimal | None:
    """'Rupees One Lakh Sixteen Thousand Three Hundred Forty Eight Only' → Decimal('116348.00')."""
    if not text:
        return None
    s = text.lower().replace("-", " ").replace(",", " ")
    s = re.sub(r"[^a-z ]", " ", s)
    words = s.split()
    if not words:
        return None
    rupee_part, paise_part = words, []
    if "paise" in words or "paisa" in words:
        end = words.index("paise") if "paise" in words else words.index("paisa")
        head = words[:end]
        # paise amount follows the last "and" (or the word "rupees" at the end of the rupee part)
        split = max((i for i, w in enumerate(head) if w == "and"), default=-1)
        if split < 0:
            return None
        rupee_part, paise_part = head[:split], head[split + 1 :]
    rupees = _words_to_int(rupee_part) if rupee_part else 0
    paise = _words_to_int(paise_part) if paise_part else 0
    if rupees is None or paise is None or paise >= 100:
        return None
    return (Decimal(rupees) + Decimal(paise) / 100).quantize(Decimal("0.01"))
