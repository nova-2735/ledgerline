"""Description normaliser and the invoice-line ↔ PO-line pair score (RULES §5 steps 1–2).

Shared by PO inference (`purchase_orders.py`) and line matching (`rules/matching.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from rapidfuzz import fuzz

from app.models.extraction import LineItem
from app.models.reference import POLine

W_DESC = 0.5
W_PRICE = 0.3
W_QTY = 0.2
PRICE_TOLERANCE = Decimal("0.05")
MATCH_THRESHOLD = 0.60

STOP_WORDS = frozenset({"of", "with", "for", "and", "the", "incl"})

# Multi-word unit spellings are unified before tokenising.
_PHRASES = (
    (re.compile(r"\bsq\s*\.?\s*mm\b"), " sqmm "),
    (re.compile(r"\bmm\s*2\b"), " sqmm "),
)
_UNITS = {
    "sqmm": "sqmm",
    "mtr": "m",
    "mtrs": "m",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "amp": "a",
    "amps": "a",
    "nos": "nos",
    "no": "nos",
}
# A number glued to a unit suffix: "32A" → "32 a", "2.5mm" → "2.5 mm".
_NUM_SUFFIX = re.compile(r"(\d)([a-z])")
_SUFFIX_NUM = re.compile(r"([a-z])(\d)")
# Punctuation, except a decimal point between digits.
_PUNCT = re.compile(r"(?!(?<=\d)\.(?=\d))[^\w\s]|_")


def normalize_description(text: str | None) -> str:
    """Lowercase, strip punctuation, split numbers from units, unify units, drop stop words."""
    if not text:
        return ""
    s = text.lower()
    s = _PUNCT.sub(" ", s)
    for pattern, repl in _PHRASES:
        s = pattern.sub(repl, s)
    s = _NUM_SUFFIX.sub(r"\1 \2", s)
    s = _SUFFIX_NUM.sub(r"\1 \2", s)
    for pattern, repl in _PHRASES:
        s = pattern.sub(repl, s)
    tokens = [_UNITS.get(t, t) for t in s.split()]
    return " ".join(t for t in tokens if t not in STOP_WORDS)


def description_similarity(invoice_desc: str | None, po_desc: str | None) -> float:
    """rapidfuzz token_set_ratio of the normalised descriptions, in [0, 1]."""
    a, b = normalize_description(invoice_desc), normalize_description(po_desc)
    if not a or not b:
        return 0.0
    return fuzz.token_set_ratio(a, b) / 100.0


def effective_unit_price(line: LineItem) -> Decimal | None:
    """Unit price before tax. For tax-inclusive lines this is taxable_amount / quantity."""
    qty = line.quantity
    inclusive = (
        line.taxable_amount is not None
        and line.amount is not None
        and line.taxable_amount != line.amount
    )
    if inclusive and qty:
        assert line.taxable_amount is not None
        return (line.taxable_amount / qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if line.unit_price is not None:
        return line.unit_price
    if line.amount is not None and qty:
        return (line.amount / qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return None


def price_within(inv_price: Decimal | None, po_price: Decimal) -> bool:
    """|inv − po| / po ≤ 5%."""
    if inv_price is None:
        return False
    if po_price == 0:
        return inv_price == 0
    return abs(inv_price - po_price) / po_price <= PRICE_TOLERANCE


@dataclass(frozen=True)
class PairScore:
    score: float
    desc: float
    price: float
    qty: float
    by_code: bool

    @property
    def matches(self) -> bool:
        return self.score >= MATCH_THRESHOLD


def pair_score(inv_line: LineItem, po_line: POLine, remaining_qty: Decimal | None) -> PairScore:
    """`0.5·desc + 0.3·price + 0.2·qty` (RULES §5 step 2).

    desc = token_set_ratio/100, or 1.0 when the item code matches exactly; price = 1 within 5% of
    the PO price; qty = 1 when the invoiced quantity fits the remaining-to-bill quantity.
    """
    by_code = bool(
        inv_line.item_code
        and inv_line.item_code.strip().upper() == po_line.item_code.strip().upper()
    )
    desc = 1.0 if by_code else description_similarity(inv_line.description, po_line.description)
    price = 1.0 if price_within(effective_unit_price(inv_line), po_line.unit_price) else 0.0
    remaining = po_line.quantity if remaining_qty is None else remaining_qty
    qty_ok = inv_line.quantity is not None and inv_line.quantity <= remaining
    qty = 1.0 if qty_ok else 0.0
    score = round(W_DESC * desc + W_PRICE * price + W_QTY * qty, 4)
    return PairScore(score=score, desc=round(desc, 4), price=price, qty=qty, by_code=by_code)
