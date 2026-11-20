from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.enums import Outcome
from app.rules import duplicates as x
from app.rules.base import ReviewOverrides
from tests.rules.builders import codes, ledger_row, line, make_ctx, make_extraction, statuses

S05 = {
    "invoice_number": "SPI-2627-187",
    "invoice_date": "03-Oct-2026",
    "po_reference": "KF-PO-0126",
    "line_items": [line("Corrugated shipper box", "1500", "38.50", code="PKG-CB-0450")],
    "subtotal": "57,750.00",
    "tax_lines": [{"tax_type": "IGST", "rate": "18%", "amount": "10,395.00"}],
    "total": "68,145.00",
    "amount_in_words": None,
}


def _s05(**kw: Any) -> Any:
    return make_extraction(**(S05 | kw))


def test_x01_same_file() -> None:
    assert statuses(x.x01_same_file(make_ctx())) == ["pass"]
    [res] = x.x01_same_file(make_ctx(file_rows=[ledger_row(7)]))
    assert res.code == "DUPLICATE_SAME_FILE" and res.outcome_hint == Outcome.REJECT
    assert res.evidence["run_id"] == 7 and res.evidence["display_id"] == "R-0007"
    assert statuses(x.x01_same_file(make_ctx(file_sha256=None))) == ["skip"]


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        ("68,145.00", ["DUPLICATE_SAME_INVOICE"]),
        ("68,146.00", ["DUPLICATE_SAME_INVOICE"]),  # ₹1 apart
        ("68,146.01", []),
    ],
)
def test_x02_same_invoice(total: str, expected: list[str]) -> None:
    ex = _s05(total=total)
    ctx = make_ctx(ex, po="KF-PO-0126", ledger_rows=[ledger_row(3)])
    assert codes(x.x02_same_invoice(ctx)) == expected


def test_x02_evidence_and_skips() -> None:
    [res] = x.x02_same_invoice(make_ctx(_s05(), po="KF-PO-0126", ledger_rows=[ledger_row(3)]))
    assert res.evidence["original_invoice_number"] == "SPI/26-27/0187"
    assert res.evidence["original_outcome"] == "APPROVE"
    assert str(res.amount_at_risk) == "68145.00"
    assert 'printed then as "SPI/26-27/0187", now as "SPI-2627-187"' in res.message
    assert statuses(x.x02_same_invoice(make_ctx(_s05(invoice_number=None)))) == ["skip"]
    assert statuses(x.x02_same_invoice(make_ctx(_s05(), vendor=None))) == ["skip"]


def test_not_duplicate_override_resolves() -> None:
    ctx = make_ctx(_s05(), ledger_rows=[ledger_row(3)], file_rows=[ledger_row(3)],
                   overrides=ReviewOverrides(not_duplicate=True))  # fmt: skip
    for fn in (x.x01_same_file, x.x02_same_invoice):
        [res] = fn(ctx)
        assert res.status.value == "fail" and res.resolved_by_review


def test_x03_ignores_rows_already_matched() -> None:
    ctx = make_ctx(_s05(), po="KF-PO-0126", ledger_rows=[ledger_row(3)])
    assert statuses(x.x03_fuzzy(ctx)) == ["pass"]


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        # similar number (one digit off), same amount, 10 days apart
        ({"invoice_number_canonical": "2627188", "invoice_date": date(2026, 9, 23)},
         ["DUPLICATE_SUSPECTED"]),
        # different number, same PO and quantities
        ({"invoice_number_canonical": "9999", "invoice_number": "X/9999"}, ["DUPLICATE_SUSPECTED"]),
        # amount 0.5% apart is still within; 0.6% is not
        ({"invoice_number_canonical": "2627188", "total": "68485.72"}, ["DUPLICATE_SUSPECTED"]),
        ({"invoice_number_canonical": "2627188", "total": "68554.00"}, []),
        # dates more than 30 days apart
        ({"invoice_number_canonical": "2627188", "invoice_date": date(2026, 8, 30)}, []),
        # different number and a different PO
        ({"invoice_number_canonical": "9999", "po_number": "KF-PO-0101"}, []),
    ],
)  # fmt: skip
def test_x03_fuzzy(kw: dict[str, Any], expected: list[str]) -> None:
    ctx = make_ctx(_s05(), po="KF-PO-0126", ledger_rows=[ledger_row(4, **kw)])
    assert codes(x.x03_fuzzy(ctx)) == expected
