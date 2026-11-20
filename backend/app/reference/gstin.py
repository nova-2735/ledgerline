"""GSTIN helpers: checksum validation, state code, PAN and single-character OCR repair."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from stdnum.in_ import gstin as gstin_mod

_CONFUSABLE_TO_DIGIT = {"O": "0", "I": "1", "S": "5", "B": "8", "Z": "2"}
_CONFUSABLE_TO_LETTER = {v: k for k, v in _CONFUSABLE_TO_DIGIT.items()}
# position → allowed kind: d = digit, a = letter, x = either
_GSTIN_SHAPE = "ddaaaaaddddaxax"
_GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


@dataclass(frozen=True)
class GstinResult:
    value: str
    valid: bool
    notes: list[str] = field(default_factory=list)


def clean(text: str) -> str:
    """Uppercase and drop spaces and hyphens."""
    return re.sub(r"[\s\-]", "", text).upper()


def validate(gstin: str | None) -> bool:
    """True when the GSTIN has the right shape and a valid checksum."""
    if not gstin:
        return False
    s = clean(gstin)
    return bool(_GSTIN_RE.match(s)) and gstin_mod.is_valid(s)


def state_code(gstin: str) -> str:
    """Two-digit state code (GSTIN[0:2])."""
    return clean(gstin)[:2]


def pan(gstin: str) -> str:
    """Embedded PAN (GSTIN[2:12])."""
    return clean(gstin)[2:12]


def repair(text: str | None) -> GstinResult | None:
    """Clean a printed GSTIN; if the checksum fails, try exactly one OCR-confusable substitution
    at a position whose kind (digit/letter) allows it. Accept only a unique repair."""
    if text is None:
        return None
    s = clean(text)
    if validate(s):
        return GstinResult(s, True)
    if len(s) != 15:
        return GstinResult(s, False)
    repairs: list[tuple[int, str]] = []
    for i, ch in enumerate(s):
        kind = _GSTIN_SHAPE[i]
        options = []
        if kind in "dx" and ch in _CONFUSABLE_TO_DIGIT:
            options.append(_CONFUSABLE_TO_DIGIT[ch])
        if kind in "ax" and ch in _CONFUSABLE_TO_LETTER:
            options.append(_CONFUSABLE_TO_LETTER[ch])
        for opt in options:
            candidate = s[:i] + opt + s[i + 1 :]
            if validate(candidate):
                repairs.append((i, candidate))
    if len(repairs) == 1:
        pos, fixed = repairs[0]
        return GstinResult(fixed, True, [f"OCR repair at position {pos + 1}"])
    return GstinResult(s, False)
