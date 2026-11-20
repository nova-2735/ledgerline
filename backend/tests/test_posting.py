from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.decide.posting import build_posting
from app.rules import matching
from tests.rules.builders import line, make_ctx, make_extraction


def test_s01_posting() -> None:
    ctx = make_ctx()
    p = build_posting(ctx.extraction, ctx.vendor, ctx.po, matching.build_view(ctx))
    assert p is not None
    assert [(ln.po_line_no, ln.gl_account, ln.cost_center) for ln in p.lines] == [
        (1, "510200", "BLR-PLANT-01"),
        (2, "510200", "BLR-PLANT-01"),
    ]
    assert [ln.taxable_amount for ln in p.lines] == [Decimal("77000.00"), Decimal("21600.00")]
    assert sum(ln.tax_amount for ln in p.lines) == Decimal("17748.00")
    assert p.due_date == date(2026, 12, 12) and p.payment_terms_days == 30
    assert p.total == Decimal("116348.00")
    assert p.remit_to["account_number"] == "50200012345678"  # vendor master, not the invoice
    assert p.remit_to["ifsc"] == "HDFC0000123"


def test_remit_to_ignores_invoice_bank() -> None:
    ex = make_extraction(bank_account_number="012345678901", bank_ifsc="YESB0000123")
    ctx = make_ctx(ex)
    p = build_posting(ex, ctx.vendor, ctx.po, matching.build_view(ctx))
    assert p is not None and p.remit_to["account_number"] == "50200012345678"


def test_s07_bundle_split_by_po_amounts() -> None:
    desc = "Nimbus WMS Enterprise - annual subscription incl. onboarding (25 users)"
    ex = make_extraction(
        invoice_number="NCS/INV/2026/0932",
        invoice_date="05 Nov 2026",
        line_items=[line(desc, "1", "400000.00", hsn="997331")],
        subtotal="400,000.00",
        tax_lines=[{"tax_type": "IGST", "rate": "18%", "amount": "72,000.00"}],
        total="472,000.00",
        amount_in_words=None,
        po_reference="KF-PO-0133",
    )
    ctx = make_ctx(ex, vendor="V005", po="KF-PO-0133")
    p = build_posting(ex, ctx.vendor, ctx.po, matching.build_view(ctx))
    assert p is not None
    assert [(ln.gl_account, ln.taxable_amount, ln.tax_amount) for ln in p.lines] == [
        ("550200", Decimal("360000.00"), Decimal("64800.00")),
        ("550300", Decimal("40000.00"), Decimal("7200.00")),
    ]
    assert p.due_date == date(2026, 12, 5)


def test_no_posting_without_vendor_or_po() -> None:
    ctx = make_ctx(vendor=None)
    assert build_posting(ctx.extraction, None, ctx.po, matching.build_view(ctx)) is None
    ctx = make_ctx(po=None)
    assert build_posting(ctx.extraction, ctx.vendor, None, matching.build_view(ctx)) is None
