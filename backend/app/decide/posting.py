"""Posting payload for an approved invoice (RULES §4): one line per mapped PO line, GL account
and cost centre from the PO, bundled lines split by the PO's expected amounts, due date from the
vendor's terms, and remit-to bank details from the vendor master (never from the invoice)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.extract.normalize import mask_account
from app.models.checks import MatchingView
from app.models.decision import PostingLine, PostingPayload
from app.models.extraction import InvoiceExtraction
from app.models.reference import PurchaseOrder, Vendor
from app.rules.base import decimal_value, q2, text_value

HUNDRED = Decimal(100)


def _split(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split `amount` in proportion to `weights`; the last part takes the rounding."""
    total = sum(weights, Decimal())
    if total == 0:
        return [amount] + [Decimal("0.00")] * (len(weights) - 1)
    parts = [q2(amount * w / total) for w in weights[:-1]]
    return [*parts, q2(amount - sum(parts, Decimal()))]


def build_posting(
    extraction: InvoiceExtraction,
    vendor: Vendor | None,
    po: PurchaseOrder | None,
    view: MatchingView | None,
) -> PostingPayload | None:
    number = text_value(extraction.invoice_number)
    inv_date = extraction.invoice_date.value
    total = decimal_value(extraction.total)
    if vendor is None or po is None or view is None or number is None or total is None:
        return None
    if not isinstance(inv_date, date):
        return None
    by_no = {pl.line_no: pl for pl in po.lines}
    invoice_lines = {ln.index: ln for ln in extraction.line_items}
    lines: list[PostingLine] = []

    def add(line_no: int, taxable: Decimal, description: str) -> None:
        pl = by_no[line_no]
        lines.append(
            PostingLine(
                po_number=po.po_number,
                po_line_no=line_no,
                gl_account=pl.gl_account,
                cost_center=po.cost_center,
                taxable_amount=taxable,
                tax_amount=q2(taxable * pl.tax_rate_pct / HUNDRED),
                description=description,
            )
        )

    for row in view.rows:
        amount = row.amount_invoice
        if amount is None:
            continue
        if row.kind == "one_to_one":
            add(row.po_line_nos[0], amount, by_no[row.po_line_nos[0]].description)
        elif row.kind == "bundled":
            weights = [q2(by_no[n].quantity * by_no[n].unit_price) for n in row.po_line_nos]
            for n, part in zip(row.po_line_nos, _split(amount, weights), strict=True):
                add(n, part, by_no[n].description)
        elif row.kind == "unmatched_invoice" and lines:
            # a small charge allowed without a PO line goes to the first line's GL account
            inv = invoice_lines.get(row.invoice_line_indexes[0])
            add(lines[0].po_line_no, amount, inv.description if inv else "Other charge")
    if not lines:
        return None

    # keep Σ tax equal to the tax on the invoice (rounding lands on the last line)
    stated_tax = extraction.tax.total_tax
    computed = sum((ln.tax_amount for ln in lines), Decimal())
    if stated_tax and abs(stated_tax - computed) <= Decimal("1.00"):
        last = lines[-1]
        lines[-1] = last.model_copy(update={"tax_amount": last.tax_amount + stated_tax - computed})

    return PostingPayload(
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
