"""Find the purchase order an invoice bills: by printed reference, or by inference (RULES §6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo.money import format_indian
from app.enums import MatchType
from app.extract.normalize import canonical_po
from app.models.checks import POCandidate
from app.models.extraction import InvoiceExtraction, LineItem
from app.models.reference import POLineBalance, PurchaseOrder
from app.orm import PurchaseOrderRow
from app.reference.ledger import Ledger
from app.reference.loader import po_from_row
from app.reference.similarity import PairScore, pair_score

W_LINES = 0.45
W_AMOUNT = 0.30
W_RECEIPT = 0.15
W_DATE = 0.10
AMOUNT_HEADROOM = Decimal("1.02")
DATE_WINDOW = timedelta(days=120)
UNKNOWN_VENDOR_CAP = 20


@dataclass(frozen=True)
class POLookup:
    po: PurchaseOrder
    vendor_mismatch: bool  # the PO belongs to another vendor, or the vendor is unknown


def get_po(session: Session, po_number: str) -> PurchaseOrder | None:
    row = session.get(PurchaseOrderRow, po_number)
    return po_from_row(row) if row else None


def find_by_reference(
    session: Session, canonical: str | None, vendor_id: str | None
) -> POLookup | None:
    """PO whose canonical number equals `canonical`; on a tie prefer the vendor's own PO."""
    if not canonical:
        return None
    rows = [
        r
        for r in session.scalars(select(PurchaseOrderRow).order_by(PurchaseOrderRow.po_number))
        if canonical_po(r.po_number) == canonical
    ]
    if not rows:
        return None
    own = [r for r in rows if vendor_id and r.vendor_id == vendor_id]
    row = own[0] if own else rows[0]
    return POLookup(
        po_from_row(row), vendor_mismatch=vendor_id is None or row.vendor_id != vendor_id
    )


def _open_pos(session: Session, vendor_id: str | None) -> list[PurchaseOrder]:
    stmt = select(PurchaseOrderRow).where(PurchaseOrderRow.status == "open")
    if vendor_id:
        stmt = stmt.where(PurchaseOrderRow.vendor_id == vendor_id)
        rows = list(session.scalars(stmt.order_by(PurchaseOrderRow.po_number)))
    else:
        order = (PurchaseOrderRow.po_date.desc(), PurchaseOrderRow.po_number)
        rows = list(session.scalars(stmt.order_by(*order).limit(UNKNOWN_VENDOR_CAP)))
    return [po_from_row(r) for r in rows]


def invoice_taxable(extraction: InvoiceExtraction) -> Decimal | None:
    """Taxable value of the invoice: Σ line taxable amounts, else the printed subtotal."""
    values = [ln.taxable_amount or ln.amount for ln in extraction.line_items]
    if values and all(v is not None for v in values):
        return sum((v for v in values if v is not None), Decimal())
    sub = extraction.subtotal.value
    return sub if isinstance(sub, Decimal) else None


def remaining_value(po: PurchaseOrder, balances: dict[int, POLineBalance]) -> Decimal:
    """Σ remaining_to_bill × unit price over the PO's lines (never below zero per line)."""
    total = Decimal()
    for ln in po.lines:
        bal = balances.get(ln.line_no)
        remaining = bal.remaining_to_bill if bal else ln.quantity
        total += max(remaining, Decimal()) * ln.unit_price
    return total.quantize(Decimal("0.01"))


def best_pairs(
    lines: list[LineItem], po: PurchaseOrder, balances: dict[int, POLineBalance]
) -> list[tuple[int | None, PairScore | None]]:
    """For each invoice line, the PO line with the highest pair score (ties → lower line_no)."""
    out: list[tuple[int | None, PairScore | None]] = []
    for inv in lines:
        best: tuple[int | None, PairScore | None] = (None, None)
        for pl in po.lines:
            bal = balances.get(pl.line_no)
            ps = pair_score(inv, pl, bal.remaining_to_bill if bal else None)
            if best[1] is None or ps.score > best[1].score:
                best = (pl.line_no, ps)
        out.append(best)
    return out


def _amount_component(taxable: Decimal | None, remaining: Decimal) -> float:
    if taxable is None:
        return 0.0
    if taxable <= remaining * AMOUNT_HEADROOM:
        return 1.0
    if remaining <= 0:
        return 0.0
    overshoot_pct = (taxable - remaining) / remaining * 100
    return max(0.0, 1.0 - float(overshoot_pct) / 10.0)


def _date_component(invoice_date: date | None, po_date: date) -> float:
    if invoice_date is None:
        return 0.0
    return 1.0 if po_date <= invoice_date <= po_date + DATE_WINDOW else 0.0


def score_po(
    extraction: InvoiceExtraction, po: PurchaseOrder, balances: dict[int, POLineBalance]
) -> POCandidate:
    """`0.45·lines + 0.30·amount + 0.15·receipt + 0.10·date` with a one-line reason."""
    lines = extraction.line_items
    n = len(lines)
    pairs = best_pairs(lines, po, balances)
    lines_c = sum(ps.score for _, ps in pairs if ps) / n if n else 0.0

    taxable = invoice_taxable(extraction)
    remaining = remaining_value(po, balances)
    amount_c = _amount_component(taxable, remaining)

    three_way = po.match_type == MatchType.three_way
    received_ok = 0
    for inv, (line_no, ps) in zip(lines, pairs, strict=True):
        if ps is None or not ps.matches or line_no is None:
            continue
        if not three_way:
            received_ok += 1
            continue
        bal = balances.get(line_no)
        unbilled = bal.received_unbilled if bal else None
        if inv.quantity is not None and unbilled is not None and inv.quantity <= unbilled:
            received_ok += 1
    receipt_c = received_ok / n if n else 0.0

    inv_date = extraction.invoice_date.value
    date_c = _date_component(inv_date if isinstance(inv_date, date) else None, po.po_date)

    score = W_LINES * lines_c + W_AMOUNT * amount_c + W_RECEIPT * receipt_c + W_DATE * date_c
    matched = sum(1 for _, ps in pairs if ps and ps.matches and ps.price == 1.0)

    parts = [f"items and prices match {matched}/{n} lines"]
    money = f"₹{format_indian(remaining)}"
    parts.append(
        f"amount fits remaining {money}" if amount_c == 1.0 else f"amount exceeds remaining {money}"
    )
    if three_way:
        if received_ok == n and n:
            parts.append("fully received")
        elif received_ok == 0:
            parts.append("no received quantity left to bill")
        else:
            parts.append(f"received for {received_ok}/{n} lines")
    else:
        parts.append("two-way PO, no receipt needed")
    if date_c == 0.0:
        parts.append("invoice date outside the PO window")

    return POCandidate(
        po_number=po.po_number,
        score=round(score, 4),
        components={
            "lines": round(lines_c, 4),
            "amount": round(amount_c, 4),
            "receipt": round(receipt_c, 4),
            "date": date_c,
        },
        reason="; ".join(parts),
    )


def infer_candidates(
    session: Session,
    extraction: InvoiceExtraction,
    vendor_id: str | None,
    ledger: Ledger | None = None,
    exclude_run_id: int | None = None,
) -> list[POCandidate]:
    """Score every open PO of the vendor (or up to 20 most recent open POs when the vendor is
    unknown), best first; ties go to the lower PO number. `exclude_run_id` leaves that run's own
    billing out of the balances (re-checking a run that was already approved)."""
    ledger = ledger or Ledger(session)
    candidates = [
        score_po(extraction, po, ledger.balance_map(po.po_number, exclude_run_id))
        for po in _open_pos(session, vendor_id)
    ]
    return sorted(candidates, key=lambda c: (-c.score, c.po_number))
