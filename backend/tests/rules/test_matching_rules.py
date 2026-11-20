from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.enums import CheckStatus, Route
from app.models.checks import CheckResult
from app.rules import matching as m
from app.rules.base import RuleContext
from tests.rules.builders import codes, line, make_ctx, make_extraction, money, statuses


def run_matching(ctx: RuleContext) -> list[CheckResult]:
    return [res for r in m.RULES for res in r(ctx)]


def _single(desc: str, q: str, rate: str, *, code: str | None = None, tax: str = "18%",
            po: str = "KF-PO-0150", vendor: str = "V001", **kw: Any) -> RuleContext:  # fmt: skip
    amount = Decimal(q) * Decimal(rate)
    ex = make_extraction(
        line_items=[line(desc, q, rate, code=code, tax=tax, uom="Roll")],
        subtotal=money(amount),
        tax_lines=[{"tax_type": "IGST", "rate": tax, "amount": money(amount * Decimal("0.18"))}],
        total=None,
        amount_in_words=None,
        po_reference=po,
    )
    return make_ctx(ex, vendor=vendor, po=po, **kw)


def test_s01_exact_match_by_code() -> None:
    ctx = make_ctx()
    results = run_matching(ctx)
    assert codes(results) == []
    view = m.build_view(ctx)
    assert [(r.kind, r.matched_by, r.po_line_nos) for r in view.rows] == [
        ("one_to_one", "code", [1]),
        ("one_to_one", "code", [2]),
    ]
    assert view.header_expected == view.header_invoiced == Decimal("98600.00")
    assert view.header_variance == 0


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        ("610.00", []),
        ("622.20", ["PRICE_VARIANCE_WITHIN_TOL"]),  # exactly +2%
        ("622.21", ["PRICE_VARIANCE_OVER_TOL", "AMOUNT_VARIANCE_OVER_TOL"]),
        ("600.00", ["PRICE_BELOW_PO"]),
    ],
)
def test_m02_unit_price_tolerance(rate: str, expected: list[str]) -> None:
    ctx = _single("Stretch wrap film 500 mm x 23 micron", "60", rate, code="PKG-SW-STR")
    assert sorted(codes(run_matching(ctx))) == sorted(expected)


def test_s12_price_and_header_amounts() -> None:
    ctx = _single("Stretch wrap film 500 mm x 23 micron", "60", "662.00", code="PKG-SW-STR")
    results = {r.code: r for r in run_matching(ctx) if r.code}
    price = results["PRICE_VARIANCE_OVER_TOL"]
    assert price.evidence["delta_pct"] == "8.52"
    assert str(price.amount_at_risk) == "3681.60"
    header = results["AMOUNT_VARIANCE_OVER_TOL"]
    assert header.evidence["delta"] == "3120.00" and str(header.amount_at_risk) == "3681.60"


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        # 12 trips @ 8,500 = 1,02,000; header limit min(2% = 2,040, 2,500) = 2,040
        ("8670.00", ["PRICE_VARIANCE_WITHIN_TOL"]),  # +2,040.00: exactly at the limit
        ("8670.01", ["PRICE_VARIANCE_OVER_TOL", "AMOUNT_VARIANCE_OVER_TOL"]),
    ],
)
def test_m03_header_boundary(rate: str, expected: list[str]) -> None:
    ctx = _single("Reefer transport Bengaluru-Hosur, 10T, per trip", "12", rate,
                  po="KF-PO-0137", vendor="V002")  # fmt: skip
    assert sorted(codes(run_matching(ctx))) == sorted(expected)


def test_s03_over_billing_amounts() -> None:
    ctx = _single("Nitrile safety gloves, food grade, box of 100", "50", "1450.00",
                  code="MRO-GLV-NIT", po="KF-PO-0119", vendor="V003",
                  billed={1: "60"}, received={1: "90"})  # fmt: skip
    found = {r.code: r for r in run_matching(ctx) if r.code}
    assert set(found) == {"QTY_EXCEEDS_PO_REMAINING", "QTY_EXCEEDS_RECEIVED"}
    assert str(found["QTY_EXCEEDS_PO_REMAINING"].amount_at_risk) == "17110.00"
    assert str(found["QTY_EXCEEDS_RECEIVED"].amount_at_risk) == "34220.00"
    assert found["QTY_EXCEEDS_RECEIVED"].route == Route.receiving
    assert "only 30 received and not yet billed" in found["QTY_EXCEEDS_RECEIVED"].message


def test_m04_m05_boundaries() -> None:
    exact = _single("Nitrile gloves", "30", "1450.00", code="MRO-GLV-NIT", po="KF-PO-0119",
                    vendor="V003", billed={1: "60"}, received={1: "90"})  # fmt: skip
    assert codes(run_matching(exact)) == []
    no_grn = _single("Nitrile gloves", "10", "1450.00", code="MRO-GLV-NIT", po="KF-PO-0119",
                     vendor="V003", received={1: "0"})  # fmt: skip
    assert codes(run_matching(no_grn)) == ["GOODS_NOT_RECEIVED"]


def test_two_way_po_needs_no_receipt() -> None:
    ctx = _single("Reefer transport", "12", "8500.00", code="LOG-RF-BLR", po="KF-PO-0137",
                  vendor="V002")  # fmt: skip
    results = run_matching(ctx)
    assert codes(results) == []
    m05 = [r for r in results if r.rule_id == "M05_received"]
    assert statuses(m05) == ["skip"]


def test_m06_tax_rate() -> None:
    ctx = _single("Stretch wrap film", "60", "610.00", code="PKG-SW-STR", tax="12%")
    assert codes(run_matching(ctx)) == ["TAX_RATE_MISMATCH"]


def test_s04_descriptions_map_by_fuzzy_and_price() -> None:
    lines = [
        line("Copper wire 2.5mm FRLS 90 mtr", "10", "2850.00", uom="Coil"),
        line("MCB 32 Amp DP", "20", "410.00"),
    ]
    ex = make_extraction(line_items=lines, subtotal="36,700.00", po_reference=None,
                         tax_lines=[{"tax_type": "IGST", "rate": "18%", "amount": "6,606.00"}],
                         total="43,306.00", amount_in_words=None)  # fmt: skip
    ctx = make_ctx(ex, vendor="V004", po="KF-PO-0151", po_method="inferred")
    results = run_matching(ctx)
    assert codes(results) == []
    assert all(
        "Against inferred PO KF-PO-0151" in r.message
        for r in results
        if r.status == CheckStatus.pass_
    )
    view = m.build_view(ctx)
    assert [(r.kind, r.matched_by, r.po_line_nos) for r in view.rows] == [
        ("one_to_one", "fuzzy", [1]),
        ("one_to_one", "fuzzy", [2]),
    ]


def test_s07_bundle_by_subset_sum() -> None:
    desc = "Nimbus WMS Enterprise - annual subscription incl. onboarding (25 users)"
    ex = make_extraction(
        line_items=[line(desc, "1", "400000.00", hsn="997331")],
        subtotal="400,000.00",
        tax_lines=[{"tax_type": "IGST", "rate": "18%", "amount": "72,000.00"}],
        total="472,000.00",
        amount_in_words=None,
        po_reference="KF-PO-0133",
    )
    ctx = make_ctx(ex, vendor="V005", po="KF-PO-0133")
    results = run_matching(ctx)
    assert codes(results) == ["LINES_BUNDLED"]
    [row] = m.build_view(ctx).rows
    assert (row.kind, row.matched_by, row.po_line_nos) == ("bundled", "bundle", [1, 2])
    assert row.amount_expected == row.amount_invoice == Decimal("400000.00")


def test_bundle_needs_matching_description_and_sum() -> None:
    ex = make_extraction(
        line_items=[line("Something unrelated", "1", "400000.00")],
        subtotal="400,000.00", tax_lines=[], total=None, amount_in_words=None,
    )  # fmt: skip
    assert "LINES_BUNDLED" not in codes(run_matching(make_ctx(ex, vendor="V005", po="KF-PO-0133")))


def test_s14_extra_line_not_on_po() -> None:
    ex = make_extraction(
        document_type="proforma_invoice",
        line_items=[
            line("Additional user licences (10 users), pro-rated to Oct 2027", "10", "14400.00")
        ],  # fmt: skip
        subtotal="144,000.00",
        tax_lines=[{"tax_type": "IGST", "rate": "18%", "amount": "25,920.00"}],
        total="169,920.00",
        amount_in_words=None,
    )
    ctx = make_ctx(ex, vendor="V005", po="KF-PO-0133")
    results = run_matching(ctx)
    assert codes(results) == ["LINE_NOT_ON_PO"]
    kinds = [r.kind for r in m.build_view(ctx).rows]
    assert kinds == ["unmatched_invoice", "unmatched_po", "unmatched_po"]


def test_small_unmatched_charge_is_allowed() -> None:
    ex = make_extraction(
        line_items=[
            line("Corrugated shipper box", "2000", "38.50", code="PKG-CB-0450"),
            line("BOPP tape", "300", "72.00", code="PKG-TP-0048", uom="Roll"),
            line("Courier charges", "1", "500.00", tax="18%"),
        ],
        subtotal=None, total=None, amount_in_words=None,
    )  # fmt: skip
    assert codes(run_matching(make_ctx(ex))) == ["MISC_CHARGE_ALLOWED"]


def test_matching_skips_without_po_or_with_wrong_vendor() -> None:
    for ctx in (make_ctx(po=None), make_ctx(vendor="V004"), make_ctx(vendor=None)):
        results = run_matching(ctx)
        assert statuses(results) == ["skip"] * len(m.RULES)
        assert m.build_view(ctx).rows == []
