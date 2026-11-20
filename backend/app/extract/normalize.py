"""Parse transcribed strings into typed values (CONTRACTS §10). The model never does this."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.reference.gstin import GstinResult
from app.reference.gstin import repair as repair_gstin

CENT = Decimal("0.01")

# --- amounts, quantities, rates ---------------------------------------------------------------

_CURRENCY = re.compile(r"(₹|\bINR\b|\bRs\b\.?|Rs\.)", re.IGNORECASE)
_NUM = re.compile(r"^\d+(?:\.\d+)?$")


def parse_amount_noted(text: str | None) -> tuple[Decimal | None, list[str]]:
    """Amount with notes ('Cr'/'Dr' suffix). Returns (None, []) for anything unparseable."""
    if text is None:
        return None, []
    s = _CURRENCY.sub("", text).strip()
    notes: list[str] = []
    m = re.search(r"\s*\b(Cr|Dr)\.?$", s, re.IGNORECASE)
    if m:
        notes.append(f"{m.group(1).capitalize()} suffix")
        s = s[: m.start()].strip()
    s = s.replace("/-", "").replace(" ", "").replace(",", "")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.endswith("-"):
        negative, s = True, s[:-1]
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if s.endswith("."):
        s = s[:-1]
    if not _NUM.match(s):
        return None, []
    value = Decimal(s).quantize(CENT, rounding=ROUND_HALF_UP)
    return (-value if negative else value), notes


def parse_amount(text: str | None) -> Decimal | None:
    return parse_amount_noted(text)[0]


def parse_quantity(text: str | None) -> tuple[Decimal | None, str | None]:
    """'2,000 Nos' → (2000, 'Nos'); '1' → (1, None)."""
    if text is None:
        return None, None
    m = re.match(r"^\s*([\d,]*\.?\d+)\s*([A-Za-z][A-Za-z .\-]*)?\s*$", text)
    if not m:
        return None, None
    try:
        qty = Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None, None
    unit = m.group(2).strip() if m.group(2) else None
    return qty, unit


def parse_rate(text: str | None) -> Decimal | None:
    """'18%', '18.0 %', '@18' → Decimal('18')."""
    if text is None:
        return None
    m = re.match(r"^\s*@?\s*(\d+(?:\.\d+)?)\s*%?\s*$", text)
    if not m:
        return None
    return Decimal(m.group(1)).normalize()


# --- dates -----------------------------------------------------------------------------------

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
AMBIGUOUS_NOTE = "ambiguous day/month, read as DMY"


@dataclass(frozen=True)
class ParsedDate:
    value: date
    notes: list[str] = field(default_factory=list)

    @property
    def ambiguous(self) -> bool:
        return AMBIGUOUS_NOTE in self.notes


def _month(name: str) -> int | None:
    key = name.lower().rstrip(".")[:3]
    return _MONTHS.get(key)


def _year(text: str) -> int:
    y = int(text)
    return 2000 + y if len(text) == 2 else y


def _make(y: int, m: int, d: int, notes: list[str]) -> ParsedDate | None:
    try:
        return ParsedDate(date(y, m, d), notes)
    except ValueError:
        return None


def parse_date(text: str | None, order: str = "DMY") -> ParsedDate | None:
    if text is None:
        return None
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.strip(), flags=re.IGNORECASE)
    if m := re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s):
        return _make(int(m[1]), int(m[2]), int(m[3]), [])
    if m := re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})$", s):
        a, b, y = int(m[1]), int(m[2]), _year(m[3])
        notes = [AMBIGUOUS_NOTE] if a <= 12 and b <= 12 and a != b else []
        d, mo = (b, a) if order == "MDY" else (a, b)
        if order == "MDY" and notes:
            notes = ["ambiguous day/month, read as MDY"]
        return _make(y, mo, d, notes)
    if m := re.match(r"^(\d{1,2})[\s\-]+([A-Za-z]{3,9})\.?[\s\-,]+(\d{4}|\d{2})$", s):
        month = _month(m[2])
        return _make(_year(m[3]), month, int(m[1]), []) if month else None
    if m := re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$", s):
        month = _month(m[1])
        return _make(int(m[3]), month, int(m[2]), []) if month else None
    return None


# --- identifiers -----------------------------------------------------------------------------


def normalize_gstin(text: str | None) -> GstinResult | None:
    """Uppercase, strip spaces/hyphens; repair exactly one OCR-confusable character if needed."""
    return repair_gstin(text)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Z]+|\d+", text.upper())


def canonical_number(text: str | None) -> str | None:
    """Invoice/PO canonical form: numeric tokens without leading zeros, concatenated."""
    if text is None:
        return None
    tokens = _tokens(text)
    numeric = [t.lstrip("0") or "0" for t in tokens if t.isdigit()]
    if numeric:
        return "".join(numeric)
    alnum = "".join(tokens)
    return alnum or None


def canonical_invoice_number(text: str | None) -> str | None:
    return canonical_number(text)


def canonical_po(text: str | None) -> str | None:
    return canonical_number(text)


def normalize_account(text: str | None) -> str | None:
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    return digits or None


def mask_account(number: str) -> str:
    return f"****{number[-4:]}"


_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def normalize_ifsc(text: str | None) -> str | None:
    if text is None:
        return None
    return re.sub(r"\s", "", text).upper() or None


def ifsc_valid(code: str | None) -> bool:
    return bool(code and _IFSC.match(code))


def bank_account_valid(number: str | None) -> bool:
    return bool(number and 9 <= len(number) <= 18)


_INVOICE_NO = re.compile(r"^[A-Z0-9/\-]{1,16}$")


def invoice_number_valid(text: str | None) -> bool:
    return bool(text and _INVOICE_NO.match(text.strip().upper()))


def currency_code(text: str | None) -> str:
    if text is None:
        return "INR"
    s = text.strip().upper().rstrip(".")
    if s in {"₹", "RS", "INR", "RUPEES", ""}:
        return "INR"
    return s
