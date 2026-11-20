from __future__ import annotations

from typing import Any

import pytest

from app.enums import Outcome, Route
from app.rules import tax as t
from tests.rules.builders import codes, line, make_ctx, make_extraction, statuses

INTRA_LINES = [line("A4 copier paper 75 GSM", "100", "245.00"), line("Toner 88A", "10", "1650.00")]


def _intra(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "supplier_gstin": "29AQZPB7715N1ZX",
        "line_items": INTRA_LINES,
        "subtotal": "41,000.00",
        "tax_lines": [
            {"tax_type": "CGST", "rate": "9%", "amount": "3,690.00"},
            {"tax_type": "SGST", "rate": "9%", "amount": "3,690.00"},
        ],
        "total": "48,380.00",
        "amount_in_words": None,
    }
    return base | kw


@pytest.mark.parametrize(
    ("gstin", "expected"),
    [
        ("27AAKFS2231P1ZS", "pass"),
        ("27AAKFS2231P1ZT", "fail"),
        ("27AAKFS2231", "fail"),
        (None, "fail"),
    ],
)
def test_t01_supplier_gstin(gstin: str | None, expected: str) -> None:
    results = t.t01_supplier_gstin(make_ctx(make_extraction(supplier_gstin=gstin)))
    assert statuses(results) == [expected]
    if expected == "fail":
        assert results[0].code == "GSTIN_INVALID" and results[0].route == Route.vendor


@pytest.mark.parametrize(
    ("buyer", "expected"),
    [
        ("29AAJCK4417M1Z1", []),
        ("29 aajck 4417 m1z1", []),
        (None, ["BUYER_GSTIN_MISMATCH"]),
        ("27AAKFS2231P1ZS", ["BUYER_GSTIN_MISMATCH"]),
    ],  # fmt: skip
)
def test_t02_buyer_gstin(buyer: str | None, expected: list[str]) -> None:
    assert codes(t.t02_buyer_gstin(make_ctx(make_extraction(buyer_gstin=buyer)))) == expected


def test_t03_inter_state_igst_passes_and_intra_igst_fails() -> None:
    assert codes(t.t03_tax_type(make_ctx())) == []
    assert codes(t.t03_tax_type(make_ctx(make_extraction(**_intra())))) == []
    s09 = make_extraction(
        **_intra(tax_lines=[{"tax_type": "IGST", "rate": "18%", "amount": "7,380.00"}])
    )
    [res] = t.t03_tax_type(make_ctx(s09, vendor="V008", po="KF-PO-0148"))
    assert res.code == "TAX_TYPE_MISMATCH" and res.outcome_hint == Outcome.RETURN
    assert "CGST 9% ₹3,690.00 + SGST 9% ₹3,690.00" in res.message
    assert "input tax credit" in res.message


def test_t03_cgst_on_inter_state_fails_and_skips() -> None:
    ex = make_extraction(
        tax_lines=[
            {"tax_type": "CGST", "rate": "9%", "amount": "8,874.00"},
            {"tax_type": "SGST", "rate": "9%", "amount": "8,874.00"},
        ]
    )
    assert codes(t.t03_tax_type(make_ctx(ex))) == ["TAX_TYPE_MISMATCH"]
    bad = make_extraction(supplier_gstin="27AAKFS2231P1ZT")
    assert statuses(t.t03_tax_type(make_ctx(bad))) == ["skip"]
    assert statuses(t.t04_tax_amount(make_ctx(bad))) == ["skip"]


@pytest.mark.parametrize(
    ("igst", "expected"),
    [
        ("17,748.00", []),
        ("17,749.00", []),  # exactly rounding_abs
        ("17,749.01", ["TAX_AMOUNT_MISMATCH"]),
        ("16,000.00", ["TAX_AMOUNT_MISMATCH"]),
    ],
)
def test_t04_igst_amount(igst: str, expected: list[str]) -> None:
    ex = make_extraction(tax_lines=[{"tax_type": "IGST", "rate": "18%", "amount": igst}])
    assert codes(t.t04_tax_amount(make_ctx(ex))) == expected


def test_t04_one_result_per_tax_type() -> None:
    results = t.t04_tax_amount(make_ctx(make_extraction(**_intra())))
    assert statuses(results) == ["pass", "pass"]
    off = _intra(
        tax_lines=[
            {"tax_type": "CGST", "rate": "9%", "amount": "3,690.00"},
            {"tax_type": "SGST", "rate": "9%", "amount": "3,600.00"},
        ]
    )
    assert codes(t.t04_tax_amount(make_ctx(make_extraction(**off)))) == ["TAX_AMOUNT_MISMATCH"]


@pytest.mark.parametrize("only", ["CGST", "SGST"])
def test_intra_state_needs_both_cgst_and_sgst(only: str) -> None:
    """Regression: a CGST-only (or SGST-only) intra-state invoice passed T03 and T04."""
    half = _intra(
        tax_lines=[{"tax_type": only, "rate": "9%", "amount": "3,690.00"}],
        total="44,690.00",
    )
    ctx = make_ctx(make_extraction(**half), vendor="V008", po="KF-PO-0148")
    [t03] = t.t03_tax_type(ctx)
    missing = "SGST" if only == "CGST" else "CGST"
    assert t03.code == "TAX_TYPE_MISMATCH" and t03.evidence["missing"] == missing
    assert f"Only {only} was charged" in t03.message
    t04 = t.t04_tax_amount(ctx)
    assert [r.evidence["tax_type"] for r in t04] == ["CGST", "SGST"]
    assert codes(t04) == ["TAX_AMOUNT_MISMATCH"]
    [bad] = [r for r in t04 if r.status.value == "fail"]
    assert bad.evidence["tax_type"] == missing and bad.evidence["actual"] == "0.00"
