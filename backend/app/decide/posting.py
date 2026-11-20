"""Posting payload for an approved invoice (RULES §4): one line per mapped PO line, GL account
and cost centre from the PO, bundled lines split by the PO's expected amounts, due date from the
vendor's terms, and remit-to bank details from the vendor master (never from the invoice).

Separately printed charges (freight, packing) and the round-off get their own lines, so the lines
always add up to the invoice total. When that isn't possible the result carries the gaps instead
of a payload, and the decision holds the invoice (A02).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.extract.normalize import mask_account
from app.models.checks import MatchingView
from app.models.decision import PostingLine, PostingPayload
from app.models.extraction import InvoiceExtraction
from app.models.reference import PurchaseOrder, Vendor
from app.rules.base import decimal_value, inr, q2, text_value

HUNDRED = Decimal(100)
ROUNDING_ABS = Decimal("1.00")  # residual a round-off line may absorb


@dataclass(frozen=True)
class PostingResult:
    posting: PostingPayload | None
    gaps: list[str] = field(default_factory=list)  # why there is no payload, in plain English


def _split(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split `amount` in proportion to `weights`; the last part takes the rounding."""
    total = sum(weights, Decimal())
    if total == 0:
        return [amount] + [Decimal("0.00")] * (len(weights) - 1)
    parts = [q2(amount * w / total) for w in weights[:-1]]
    return [*parts, q2(amount - sum(parts, Decimal()))]


def _header_gaps(
    extraction: InvoiceExtraction,
    vendor: Vendor | None,
    po: PurchaseOrder | None,
    view: MatchingView | None,
) -> list[str]:
    gaps = []
    if vendor is None:
        gaps.append("the vendor isn't in the vendor master")
    if po is None:
        gaps.append("no purchase order is resolved")
    elif view is None or view.po_number != po.po_number:
        gaps.append(f"the lines haven't been matched to {po.po_number}")
    if text_value(extraction.invoice_number) is None:
        gaps.append("the invoice number is missing")
    if not isinstance(extraction.invoice_date.value, date):
        gaps.append("the invoice date is missing")
    if decimal_value(extraction.total) is None:
        gaps.append("the invoice total is missing")
    return gaps


def posting_for(
    extraction: InvoiceExtraction,
    vendor: Vendor | None,
    po: PurchaseOrder | None,
    view: MatchingView | None,
) -> PostingResult:
    gaps = _header_gaps(extraction, vendor, po, view)
    if gaps:
        return PostingResult(None, gaps)
    assert vendor is not None and po is not None and view is not None
    number = text_value(extraction.invoice_number)
    inv_date = extraction.invoice_date.value
    total = decimal_value(extraction.total)
    assert number is not None and isinstance(inv_date, date) and total is not None

    by_no = {pl.line_no: pl for pl in po.lines}
    invoice_lines = {ln.index: ln for ln in extraction.line_items}
    lines: list[PostingLine] = []

    def add(line_no: int, taxable: Decimal, description: str, *, taxed: bool = True) -> None:
        pl = by_no[line_no]
        lines.append(
            PostingLine(
                po_number=po.po_number,
                po_line_no=line_no,
                gl_account=pl.gl_account,
                cost_center=po.cost_center,
                taxable_amount=taxable,
                tax_amount=q2(taxable * pl.tax_rate_pct / HUNDRED) if taxed else Decimal("0.00"),
                description=description,
            )
        )

    small_charges = []
    for row in view.rows:
        amount = row.amount_invoice
        if row.kind == "unmatched_po":
            continue
        if amount is None:
            where = ", ".join(str(i + 1) for i in row.invoice_line_indexes)
            gaps.append(f"the amount of invoice line {where} couldn't be read")
            continue
        if row.kind == "one_to_one":
            add(row.po_line_nos[0], amount, by_no[row.po_line_nos[0]].description)
        elif row.kind == "bundled":
            weights = [q2(by_no[n].quantity * by_no[n].unit_price) for n in row.po_line_nos]
            for n, part in zip(row.po_line_nos, _split(amount, weights), strict=True):
                add(n, part, by_no[n].description)
        else:
            small_charges.append(row)
    if not lines:
        gaps.append(f"no invoice line maps to a line of {po.po_number}")
    if gaps:
        return PostingResult(None, gaps)

    # a small charge allowed without a PO line goes to the first line's GL account
    first = lines[0].po_line_no
    for row in small_charges:
        inv = invoice_lines.get(row.invoice_line_indexes[0])
        add(first, row.amount_invoice or Decimal(0), inv.description if inv else "Other charge")

    # keep Σ tax equal to the tax on the invoice (rounding lands on the last line)
    stated_tax = extraction.tax.total_tax
    computed = sum((ln.tax_amount for ln in lines), Decimal())
    if stated_tax and abs(stated_tax - computed) <= ROUNDING_ABS:
        last = lines[-1]
        lines[-1] = last.model_copy(update={"tax_amount": last.tax_amount + stated_tax - computed})

    # separately printed charges (freight, packing …), untaxed: their GST is in the stated tax
    other = extraction.other_charges_total
    if other:
        labels = [c.label.strip() for c in extraction.meta.raw.other_charges if c.label.strip()]
        add(first, other, "Other charges: " + ", ".join(labels) if labels else "Other charges",
            taxed=False)  # fmt: skip

    # the round-off, plus any rounding difference left over, so the lines add up to the total
    round_off = decimal_value(extraction.round_off) or Decimal("0.00")
    posted = sum((ln.taxable_amount + ln.tax_amount for ln in lines), Decimal()) + round_off
    residual = q2(total - posted)
    if abs(residual) > ROUNDING_ABS:
        gaps.append(
            f"the posting lines come to {inr(posted)} but the invoice total is {inr(total)}"
        )
        return PostingResult(None, gaps)
    if round_off + residual:
        add(first, q2(round_off + residual), "Round-off", taxed=False)

    return PostingResult(
        PostingPayload(
            vendor_id=vendor.vendor_id,
            invoice_number=number,
            invoice_date=inv_date,
            due_date=inv_date + timedelta(days=vendor.payment_terms_days),
            currency=extraction.currency,
            lines=lines,
            total=total,
            payment_terms_days=vendor.payment_terms_days,
            remit_to={
                "account_name": vendor.legal_name,
                "bank_name": vendor.bank_name,
                "account_number": vendor.bank_account_number,
                "account_masked": mask_account(vendor.bank_account_number),
                "ifsc": vendor.bank_ifsc,
            },
        )
    )


def build_posting(
    extraction: InvoiceExtraction,
    vendor: Vendor | None,
    po: PurchaseOrder | None,
    view: MatchingView | None,
) -> PostingPayload | None:
    return posting_for(extraction, vendor, po, view).posting


def posted_total(posting: PostingPayload) -> Decimal:
    """Σ (taxable + tax) over the posting lines; equals `posting.total` by construction."""
    return sum((ln.taxable_amount + ln.tax_amount for ln in posting.lines), Decimal())
