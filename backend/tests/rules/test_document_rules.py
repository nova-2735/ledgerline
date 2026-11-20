from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.enums import CheckStatus, Outcome, Route, Severity
from app.rules import document as d
from app.rules.base import ReviewOverrides
from tests.rules.builders import codes, line, make_ctx, make_extraction, statuses, with_confidence


def test_clean_s01_passes_every_document_rule() -> None:
    ctx = make_ctx()
    for r in d.RULES:
        results = r(ctx)
        assert results, r.rule_id
        assert codes(results) == [], (r.rule_id, results)


@pytest.mark.parametrize(
    ("doc_type", "code", "route", "hint"),
    [
        ("tax_invoice", None, None, None),
        ("proforma_invoice", "DOC_PROFORMA", Route.vendor, Outcome.RETURN),
        ("credit_note", "DOC_CREDIT_NOTE", Route.ap_clerk, Outcome.HOLD),
        ("debit_note", "DOC_CREDIT_NOTE", Route.ap_clerk, Outcome.HOLD),
        ("purchase_order", "DOC_NOT_INVOICE", Route.none, Outcome.REJECT),
        ("statement", "DOC_NOT_INVOICE", Route.none, Outcome.REJECT),
    ],
)
def test_d01_doc_type(doc_type: str, code: str | None, route: Route, hint: Outcome) -> None:
    [res] = d.d01_doc_type(make_ctx(make_extraction(document_type=doc_type)))
    if code is None:
        assert res.status == CheckStatus.pass_
    else:
        assert (res.code, res.route, res.outcome_hint) == (code, route, hint)
        assert res.severity == Severity.high


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, []),
        ({"total": None, "invoice_number": None, "legibility": "poor"}, ["DOC_UNREADABLE"]),
        ({"total": None, "invoice_number": None, "legibility": "partly_legible"}, []),
        ({"total": None, "legibility": "poor"}, []),
    ],
)
def test_d00_legible(overrides: dict[str, Any], expected: list[str]) -> None:
    assert codes(d.d00_legible(make_ctx(make_extraction(**overrides)))) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, []),
        ({"invoice_number": None}, ["FIELD_MISSING_INVOICE_NUMBER"]),
        ({"invoice_date": None}, ["FIELD_MISSING_INVOICE_DATE"]),
        ({"total": None}, ["FIELD_MISSING_TOTAL"]),
        ({"supplier_name": None, "supplier_gstin": None}, ["FIELD_MISSING_SUPPLIER"]),
        ({"supplier_name": None}, []),
        (
            {"invoice_number": None, "total": None},
            ["FIELD_MISSING_INVOICE_NUMBER", "FIELD_MISSING_TOTAL"],
        ),
    ],
)
def test_d02_required(overrides: dict[str, Any], expected: list[str]) -> None:
    results = d.d02_required(make_ctx(make_extraction(**overrides)))
    assert len(results) == 4
    assert codes(results) == expected
    assert all(r.outcome_hint == Outcome.RETURN for r in results if r.status == CheckStatus.fail)


def test_d03_confidence_threshold_boundary() -> None:
    at = with_confidence(make_extraction(), "invoice_number", 0.80)
    assert codes(d.d03_confidence(make_ctx(at))) == []
    below = with_confidence(make_extraction(), "invoice_number", 0.79)
    [res] = d.d03_confidence(make_ctx(below))
    assert res.code == "FIELD_LOW_CONFIDENCE" and res.route == Route.ap_clerk
    assert [f["field"] for f in res.evidence["fields"]] == ["invoice_number"]


def test_d03_ignores_missing_fields_and_honours_review() -> None:
    ex = with_confidence(make_extraction(invoice_number=None), "invoice_number", 0.0)
    assert codes(d.d03_confidence(make_ctx(ex))) == []
    low = with_confidence(make_extraction(), "total", 0.5)
    ok = ReviewOverrides(fields_verified=True)
    [res] = d.d03_confidence(make_ctx(low, overrides=ok))
    assert res.status == CheckStatus.fail and res.resolved_by_review


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("77,000.00", []),
        ("77,001.00", []),  # ₹1 off: within max(₹1, 0.1%)
        ("77,077.00", []),  # exactly 0.1%
        ("77,078.00", ["MATH_LINE_MISMATCH"]),
    ],
)
def test_d04_line_math(amount: str, expected: list[str]) -> None:
    lines = [line("Box", "2000", "38.50", amount=amount)]
    ex = make_extraction(line_items=lines, subtotal=None, total=None)
    assert codes(d.d04_line_math(make_ctx(ex))) == expected


@pytest.mark.parametrize(
    ("subtotal", "expected", "status"),
    [
        ("98,600.00", [], "pass"),
        ("98,601.00", [], "pass"),  # exactly rounding_abs
        ("98,601.01", ["MATH_SUBTOTAL_MISMATCH"], "fail"),
        (None, [], "skip"),
    ],
)
def test_d05_subtotal(subtotal: str | None, expected: list[str], status: str) -> None:
    results = d.d05_subtotal(make_ctx(make_extraction(subtotal=subtotal)))
    assert codes(results) == expected and statuses(results) == [status]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, []),
        ({"total": "1,16,349.00"}, []),
        ({"total": "1,16,349.01"}, ["MATH_TOTAL_MISMATCH"]),
        ({"round_off": "+0.40", "total": "1,16,348.40"}, ["ROUND_OFF_APPLIED"]),
        ({"round_off": "-1.00", "total": "1,16,347.00"}, ["ROUND_OFF_APPLIED"]),
        ({"round_off": "2.00", "total": "1,16,350.00"}, []),
    ],
)
def test_d06_total(overrides: dict[str, Any], expected: list[str]) -> None:
    assert codes(d.d06_total(make_ctx(make_extraction(**overrides)))) == expected


def test_d06_inclusive_prices_warn_and_check_total() -> None:
    lines = [line("Housekeeping", "1", "100000.00", tax=None)]
    ex = make_extraction(
        line_items=lines,
        subtotal=None,
        prices_include_tax=True,
        tax_lines=[
            {"tax_type": "CGST", "rate": "9%", "amount": "7,627.12"},
            {"tax_type": "SGST", "rate": "9%", "amount": "7,627.12"},
        ],
        total="1,00,000.00",
        amount_in_words=None,
    )
    results = d.d06_total(make_ctx(ex))
    assert codes(results) == ["TAX_INCLUSIVE_NORMALIZED"]
    assert "₹84,745.76" in results[-1].message


def test_d06_failure_carries_amount() -> None:
    [res] = d.d06_total(make_ctx(make_extraction(total="1,20,000.00")))
    assert res.amount_at_risk is not None and str(res.amount_at_risk) == "3652.00"


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("Rupees One Lakh Sixteen Thousand Three Hundred Forty Eight Only", []),
        ("Rupees One Lakh Sixteen Thousand Only", ["TOTAL_WORDS_MISMATCH"]),
        (None, []),
    ],
)
def test_d07_words(words: str | None, expected: list[str]) -> None:
    assert codes(d.d07_words(make_ctx(make_extraction(amount_in_words=words)))) == expected


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("20/11/2026", []),  # today
        ("21/11/2026", ["DATE_IN_FUTURE"]),
        ("24/05/2026", []),  # exactly 180 days old
        ("23/05/2026", ["DATE_STALE"]),
    ],
)
def test_d08_dates(printed: str, expected: list[str]) -> None:
    ctx = make_ctx(make_extraction(invoice_date=printed), today=date(2026, 11, 20))
    assert codes(d.d08_dates(ctx)) == expected
