from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.decide.posting import build_posting, posting_for
from app.models.decision import PostingPayload
from app.rules import matching
from tests.rules.builders import S01_LINES, line, make_ctx, make_extraction


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


def _posted(p: PostingPayload) -> Decimal:
    return sum((ln.taxable_amount + ln.tax_amount for ln in p.lines), Decimal())


def test_other_charges_are_posted_so_lines_add_up() -> None:
    """Regression: a separate ₹250 freight charge was left out, so the lines summed to
    ₹1,16,348.00 against a ₹1,16,598.00 total."""
    ex = make_extraction(
        other_charges=[{"label": "Freight", "amount": "250.00"}],
        total="1,16,598.00",
        amount_in_words=None,
    )
    ctx = make_ctx(ex)
    p = build_posting(ex, ctx.vendor, ctx.po, matching.build_view(ctx))
    assert p is not None and p.total == Decimal("116598.00")
    assert _posted(p) == p.total
    freight = p.lines[-1]
    assert freight.description == "Other charges: Freight"
    assert (freight.taxable_amount, freight.tax_amount) == (Decimal("250.00"), Decimal("0.00"))
    assert freight.gl_account == p.lines[0].gl_account


def test_round_off_gets_its_own_line() -> None:
    ex = make_extraction(round_off="0.40", total="1,16,348.40", amount_in_words=None)
    ctx = make_ctx(ex)
    p = build_posting(ex, ctx.vendor, ctx.po, matching.build_view(ctx))
    assert p is not None and _posted(p) == Decimal("116348.40")
    assert (p.lines[-1].description, p.lines[-1].taxable_amount) == ("Round-off", Decimal("0.40"))


def test_unread_line_amount_gives_no_posting_and_says_why() -> None:
    lines = [dict(S01_LINES[0]), dict(S01_LINES[1], amount=None)]
    ex = make_extraction(line_items=lines)
    ctx = make_ctx(ex)
    result = posting_for(ex, ctx.vendor, ctx.po, matching.build_view(ctx))
    assert result.posting is None
    assert result.gaps == ["the amount of invoice line 2 couldn't be read"]


def test_lines_that_dont_reach_the_total_give_no_posting() -> None:
    ex = make_extraction(total="1,20,000.00", amount_in_words=None)
    ctx = make_ctx(ex)
    result = posting_for(ex, ctx.vendor, ctx.po, matching.build_view(ctx))
    assert result.posting is None
    assert result.gaps == [
        "the posting lines come to ₹1,16,348.00 but the invoice total is ₹1,20,000.00"
    ]
