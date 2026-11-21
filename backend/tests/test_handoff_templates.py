from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import pytest

from app.decide.handoff import TEMPLATES, Facts, build_handoff, template_for
from app.decide.messages import internal_note, vendor_email
from app.enums import CheckStatus, Outcome, ReasonCode, Route, Severity, StageName
from app.models.checks import CheckResult
from tests.rules.builders import make_ctx, make_extraction

C = ReasonCode
LEFTOVER = re.compile(r"\{[a-z_]+\}")

# Evidence as the rules produce it, plus numbers the rendered text must contain.
CASES: dict[ReasonCode, tuple[dict[str, Any], list[str]]] = {
    C.BANK_DETAILS_CHANGED: (
        {"invoice": {"account": "****8901", "bank_name": "YES Bank", "phone": "+91 79 4000 9911"},
         "on_file": {"phone": "+91 79 2658 3300"}},
        ["****8901", "YES Bank", "+91 79 2658 3300", "+91 79 4000 9911"],
    ),
    C.PO_INFERRED: (
        {"po_number": "KF-PO-0142",
         "candidates": [{"po_number": "KF-PO-0142", "score": 0.9635},
                        {"po_number": "KF-PO-0150", "score": 0.3}]},
        ["KF-PO-0142", "Vikram Shetty", "28 Oct 2026", "2 open POs", "0.96"],
    ),
    C.PO_AMBIGUOUS: (
        {"candidates": [{"po_number": "KF-PO-0142", "score": 0.8},
                        {"po_number": "KF-PO-0150", "score": 0.78}]},
        ["KF-PO-0142", "KF-PO-0150"],
    ),
    C.PO_MISSING: ({"candidates": []}, ["the buyer"]),
    C.PO_NOT_FOUND: ({"candidates": []}, ["the buyer"]),
    C.QTY_EXCEEDS_PO_REMAINING: (
        {"po_number": "KF-PO-0142", "line_no": 1, "expected": "1500", "actual": "2000"},
        ["2000 Nos", "line 1", "1500 remain", "₹68,145.00", "credit note for 500"],
    ),
    C.QTY_EXCEEDS_RECEIVED: (
        {"po_number": "KF-PO-0142", "line_no": 2, "received": "250"}, ["line 2", "250 received"]
    ),
    C.GOODS_NOT_RECEIVED: (
        {"po_number": "KF-PO-0142", "line_no": 2, "received": "0"}, ["line 2", "0 received"]
    ),
    C.PRICE_VARIANCE_OVER_TOL: (
        {"expected": "38.50", "actual": "40.00", "delta_pct": "3.90", "invoice_line": 1},
        ["₹40.00", "₹38.50", "3.90%", "₹3,000.00", "₹3,540.00"],
    ),
    C.AMOUNT_VARIANCE_OVER_TOL: (
        {"expected": "98600.00", "actual": "101600.00", "delta_pct": "3.04"},
        ["₹1,01,600.00", "₹98,600.00", "3.04%", "₹3,000.00"],
    ),
    C.TAX_TYPE_MISMATCH: (
        {"expected": "CGST+SGST", "expected_cgst_sgst_each": {"18": "3690.00"}},
        ["CGST 9% ₹3,690.00 + SGST 9% ₹3,690.00"],
    ),
    C.FIELD_MISSING_INVOICE_NUMBER: ({"field": "invoice_number"}, ["an invoice number"]),
    C.FIELD_MISSING_INVOICE_DATE: ({"field": "invoice_date"}, ["an invoice date"]),
    C.FIELD_MISSING_TOTAL: ({"field": "total"}, ["the invoice total"]),
    C.FIELD_MISSING_SUPPLIER: ({"field": "supplier"}, ["the supplier's name and GSTIN"]),
    C.DUPLICATE_SAME_INVOICE: (
        {"original_invoice_number": "SPI/26-27/0187", "original_outcome": "APPROVE",
         "processed_at": "2026-10-06T08:12:00+00:00", "display_id": "R-0011", "run_id": 11},
        ["SPI/26-27/0187", "approved", "06 Oct 2026", "R-0011"],
    ),
    C.DUPLICATE_SAME_FILE: (
        {"original_invoice_number": "SPI/26-27/0198", "original_outcome": "APPROVE",
         "processed_at": "2026-10-21T08:00:00+00:00", "display_id": "R-0014", "run_id": 14},
        ["SPI/26-27/0198", "21 Oct 2026", "R-0014"],
    ),
    C.DUPLICATE_SUSPECTED: (
        {"original_invoice_number": "SPI/26-27/0188", "original_date": "2026-10-03",
         "original_total": "68145.00"},
        ["SPI/26-27/0188", "03 Oct 2026", "₹68,145.00"],
    ),
    C.VENDOR_NOT_FOUND: ({}, ["Sharma Packaging Industries"]),
    C.VENDOR_BLOCKED: ({"block_reason": "Failed food-safety audit"}, ["Failed food-safety audit"]),
    C.FIELD_LOW_CONFIDENCE: (
        {"fields": [{"field": "total", "label": "total"}, {"field": "invoice_date",
                                                         "label": "invoice date"}]},
        ["total, invoice date"],
    ),
    C.APPROVAL_LIMIT_EXCEEDED: ({}, ["₹1,16,348.00", "₹5,00,000.00"]),
    C.POSTING_INCOMPLETE: (
        {"gaps": ["the amount of invoice line 2 couldn't be read"]},
        ["the amount of invoice line 2 couldn't be read"],
    ),
    C.DOC_PROFORMA: ({}, ["tax invoice"]),
    C.DOC_CREDIT_NOTE: ({}, ["credit note", "₹1,16,348.00", "next payment"]),
    C.DOC_NOT_INVOICE: ({}, ["not an invoice", "nothing to pay"]),
    C.DOC_MULTIPLE_INVOICES: (
        {"invoices": ["RSE/0466", "RSE/0467"]}, ["2 invoices", "RSE/0466 and RSE/0467"]
    ),
    C.CURRENCY_MISMATCH: ({"expected": "INR", "actual": "USD"}, ["USD", "exchange rate"]),
}  # fmt: skip


def _check(code: ReasonCode, evidence: dict[str, Any], **kw: Any) -> CheckResult:
    base: dict[str, Any] = {
        "rule_id": "X",
        "stage": StageName.match_lines,
        "status": CheckStatus.fail,
        "code": code,
        "severity": Severity.medium,
        "title": "t",
        "message": f"{code.value} happened.",
        "evidence": evidence,
        "route": Route.buyer,
        "outcome_hint": Outcome.HOLD,
        "amount_at_risk": None,
    }
    if code == C.PRICE_VARIANCE_OVER_TOL:
        base["amount_at_risk"] = Decimal("3540.00")
    return CheckResult.model_validate(base | kw)


def _facts(**kw: Any) -> Facts:
    ctx = make_ctx(**kw)
    return Facts.build(ctx.extraction, ctx, Decimal("500000.00"))


def test_every_template_code_has_a_case() -> None:
    assert set(TEMPLATES) == set(CASES)


@pytest.mark.parametrize("code", list(CASES))
def test_template_renders_with_numbers(code: ReasonCode) -> None:
    evidence, expected = CASES[code]
    check = _check(code, evidence)
    facts = _facts(billed={1: "500"}) if code == C.QTY_EXCEEDS_PO_REMAINING else _facts()
    plan = build_handoff(check, [check], facts, check.route)
    text = f"{plan.handoff.question} {plan.handoff.suggested_action}"
    assert not LEFTOVER.search(text), text
    for needle in expected:
        assert needle in text, (needle, text)
    assert plan.handoff.actions == list(TEMPLATES[code].actions)
    assert plan.handoff.blocking_codes == [code]
    vendor = vendor_email(plan, facts, Outcome.RETURN, [check])
    note = internal_note(plan, facts)
    for msg in (vendor, note):
        if msg is not None:
            assert not LEFTOVER.search(msg.body) and not LEFTOVER.search(msg.subject)
    if TEMPLATES[code].draft == "vendor":
        assert vendor is not None and vendor.to == "accounts@sharmapackaging.example"
        assert len(vendor.body.split()) <= 120
    if TEMPLATES[code].draft == "internal":
        assert note is not None and note.channel == "internal"


def test_s03_partial_amount() -> None:
    check = _check(
        C.QTY_EXCEEDS_PO_REMAINING,
        {"po_number": "KF-PO-0119", "line_no": 1, "expected": "40", "actual": "50"},
    )
    facts = _facts(vendor="V003", po="KF-PO-0119", billed={1: "60"}, received={1: "90"})
    h = build_handoff(check, [check], facts, Route.buyer).handoff
    assert "only 40 remain on the PO and 30 are received and unbilled" in h.question
    assert h.suggested_action == (
        "Approve 30 Box (₹51,330.00 incl. tax) and request a credit note for 20."
    )


def test_vendor_email_goes_to_master_address_not_invoice() -> None:
    ex = make_extraction(supplier_email="billing@lookalike.example")
    ctx = make_ctx(ex)
    facts = Facts.build(ex, ctx, Decimal("500000.00"))
    check = _check(C.TAX_TYPE_MISMATCH, CASES[C.TAX_TYPE_MISMATCH][0], route=Route.vendor,
                   outcome_hint=Outcome.RETURN)  # fmt: skip
    msg = vendor_email(build_handoff(check, [check], facts, Route.vendor), facts,
                       Outcome.RETURN, [check])  # fmt: skip
    assert msg is not None and msg.to == "accounts@sharmapackaging.example"
    assert msg.subject == "Invoice SPI/26-27/0214 — action needed (wrong GST type)"


def test_bank_change_never_emails_the_vendor() -> None:
    bank = _check(C.BANK_DETAILS_CHANGED, CASES[C.BANK_DETAILS_CHANGED][0],
                  severity=Severity.critical, route=Route.treasury)  # fmt: skip
    tax = _check(C.TAX_TYPE_MISMATCH, CASES[C.TAX_TYPE_MISMATCH][0], route=Route.vendor,
                 outcome_hint=Outcome.RETURN)  # fmt: skip
    facts = _facts()
    for primary in (bank, tax):
        plan = build_handoff(primary, [bank, tax], facts, primary.route)
        assert vendor_email(plan, facts, Outcome.HOLD, [bank, tax]) is None
    note = internal_note(build_handoff(bank, [bank], facts, Route.treasury), facts)
    assert note is not None and note.to == "Treasury"


def test_unlisted_codes_fall_back_by_route() -> None:
    vendor_side = _check(C.MATH_TOTAL_MISMATCH, {}, route=Route.vendor, outcome_hint=Outcome.RETURN)
    internal = _check(C.PO_CLOSED, {})
    for check in (vendor_side, internal):
        plan = build_handoff(check, [check], _facts(), check.route)
        assert check.message in plan.handoff.question + plan.handoff.suggested_action
        assert template_for(check) is not None
