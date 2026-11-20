"""Money helpers for printing invoices: Indian and western grouping, amount in words, round-off."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from num2words import num2words

CENT = Decimal("0.01")
RUPEE = Decimal("1")


def q2(value: Decimal) -> Decimal:
    """Quantise to 2 dp, half-up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _split(value: Decimal, dp: int) -> tuple[str, str, str]:
    sign = "-" if value < 0 else ""
    text = f"{abs(value):.{dp}f}"
    whole, _, frac = text.partition(".")
    return sign, whole, frac


def _join(sign: str, grouped: str, frac: str) -> str:
    return f"{sign}{grouped}.{frac}" if frac else f"{sign}{grouped}"


def format_indian(value: Decimal, dp: int = 2) -> str:
    """1,16,348.00 — last three digits, then groups of two."""
    sign, whole, frac = _split(value, dp)
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        pairs: list[str] = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        whole = ",".join([*pairs, tail])
    return _join(sign, whole, frac)


def format_western(value: Decimal, dp: int = 2) -> str:
    """116,348.00 — groups of three."""
    sign, whole, frac = _split(value, dp)
    return _join(sign, f"{int(whole):,}", frac)


def format_amount(value: Decimal, style: str, dp: int = 2) -> str:
    if style == "indian":
        return format_indian(value, dp)
    if style == "western":
        return format_western(value, dp)
    raise ValueError(f"unknown amount style: {style}")


def _title_words(n: int) -> str:
    words = num2words(n, lang="en_IN").replace(",", "")
    out = []
    for word in words.split():
        if word == "and":
            out.append(word)
        else:
            out.append("-".join(part.capitalize() for part in word.split("-")))
    return " ".join(out)


def amount_in_words(value: Decimal) -> str:
    """Indian-system words, e.g. 'Rupees One Lakh Sixteen Thousand … Forty-Eight Only'."""
    value = q2(value)
    if value < 0:
        raise ValueError("amount in words needs a non-negative amount")
    rupees = int(value)
    paise = int((value - rupees) * 100)
    text = f"Rupees {_title_words(rupees)}"
    if paise:
        text += f" and {_title_words(paise)} Paise"
    return f"{text} Only"


def round_off(amount: Decimal) -> tuple[Decimal, Decimal]:
    """Round a 2 dp amount to the rupee. Returns (rounded total, round-off delta)."""
    exact = q2(amount)
    rounded = exact.quantize(RUPEE, rounding=ROUND_HALF_UP)
    return q2(rounded), q2(rounded - exact)


def format_signed(value: Decimal) -> str:
    """Round-off as printed: '+0.40' / '-0.20'."""
    return f"{'+' if value >= 0 else '-'}{abs(q2(value)):.2f}"
