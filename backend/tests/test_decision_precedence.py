from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.decide.decision import decide, evaluate, order_key
from app.enums import CheckStatus, Outcome, ReasonCode, Route, Severity, StageName
from app.models.checks import CheckResult
from app.models.decision import Decision
from app.models.extraction import InvoiceExtraction
from app.rules.registry import flatten, run_all
from tests.rules.builders import S01_LINES, make_ctx, make_extraction, policy

C = ReasonCode
AT = datetime(2026, 11, 20, 6, 0, tzinfo=UTC)


def chk(
    code: ReasonCode | None,
    *,
    status: CheckStatus = CheckStatus.fail,
    severity: Severity = Severity.medium,
    hint: Outcome | None = Outcome.HOLD,
    route: Route = Route.buyer,
    stage: StageName = StageName.match_lines,
    rule_id: str = "M02_unit_price",
    resolved: bool = False,
    at_risk: str | None = None,
) -> CheckResult:
    return CheckResult(
        rule_id=rule_id,
        stage=stage,
        status=status,
        code=code,
        severity=severity,
        title=f"{code.value if code else 'ok'} title",
        message=f"{code.value if code else 'ok'} message.",
        evidence={},
        route=route,
        outcome_hint=hint if status == CheckStatus.fail else None,
        amount_at_risk=Decimal(at_risk) if at_risk else None,
        resolved_by_review=resolved,
    )


PASS = chk(None, status=CheckStatus.pass_, hint=None)
REJECT = chk(C.VENDOR_BLOCKED, severity=Severity.high, hint=Outcome.REJECT, route=Route.none,
             stage=StageName.identify_vendor, rule_id="V02_status")  # fmt: skip
CRITICAL = chk(C.BANK_DETAILS_CHANGED, severity=Severity.critical, route=Route.treasury,
               stage=StageName.identify_vendor, rule_id="V04_bank_details")  # fmt: skip
RETURN = chk(C.TAX_TYPE_MISMATCH, severity=Severity.high, hint=Outcome.RETURN, route=Route.vendor,
             stage=StageName.check_tax, rule_id="T03_tax_type")  # fmt: skip
HOLD = chk(C.PRICE_VARIANCE_OVER_TOL)
WARN = chk(C.ROUND_OFF_APPLIED, status=CheckStatus.warn, severity=Severity.info,
           stage=StageName.validate_document, rule_id="D06_total")  # fmt: skip


def _decide(checks: list[CheckResult], total: str = "1,16,348.00"):  # type: ignore[no-untyped-def]
    return decide(checks, make_extraction(total=total), policy(), 1, decided_at=AT, polish=False)


@pytest.mark.parametrize(
    ("checks", "outcome", "route", "primary"),
    [
        ([PASS], Outcome.APPROVE, Route.none, None),
        ([PASS, WARN], Outcome.APPROVE, Route.none, C.ROUND_OFF_APPLIED),
        ([CRITICAL, REJECT, RETURN], Outcome.REJECT, Route.none, C.VENDOR_BLOCKED),
        ([RETURN, CRITICAL], Outcome.HOLD, Route.treasury, C.BANK_DETAILS_CHANGED),
        ([HOLD, RETURN], Outcome.RETURN, Route.vendor, C.TAX_TYPE_MISMATCH),
        ([HOLD, WARN], Outcome.HOLD, Route.buyer, C.PRICE_VARIANCE_OVER_TOL),
        # resolved checks are ignored
        ([chk(C.BANK_DETAILS_CHANGED, severity=Severity.critical, resolved=True)], Outcome.APPROVE,
         Route.none, None),
        ([REJECT.model_copy(update={"resolved_by_review": True}), HOLD], Outcome.HOLD, Route.buyer,
         C.PRICE_VARIANCE_OVER_TOL),
    ],
)  # fmt: skip
def test_precedence(
    checks: list[CheckResult], outcome: Outcome, route: Route, primary: ReasonCode | None
) -> None:
    d = _decide(checks)
    assert (d.outcome, d.route, d.primary_reason) == (outcome, route, primary)
    assert d.final is (outcome in (Outcome.APPROVE, Outcome.REJECT))


def test_approval_limit_only_when_otherwise_approve() -> None:
    big = "7,31,600.00"
    d = _decide([PASS], total=big)
    assert (d.outcome, d.route, d.reasons) == (Outcome.HOLD, Route.controller,
                                              [C.APPROVAL_LIMIT_EXCEEDED])  # fmt: skip
    assert d.headline == "Hold — Above the auto-approval limit"
    held = _decide([HOLD], total=big)
    assert C.APPROVAL_LIMIT_EXCEEDED not in held.reasons
    exactly = _decide([PASS], total="5,00,000.00")
    assert exactly.outcome == Outcome.APPROVE
    # the limit sorts after every other failing check
    r = evaluate([PASS, WARN], make_extraction(total=big), policy(), decided_at=AT, polish=False)
    assert [c.rule_id for c in r.checks][-1] == "A01_approval_limit"
    assert r.decision.reasons == [C.APPROVAL_LIMIT_EXCEEDED, C.ROUND_OFF_APPLIED]


def test_ordering_tie_breaks() -> None:
    high_late = chk(C.QTY_EXCEEDS_PO_REMAINING, severity=Severity.high, rule_id="M04_po_remaining")
    med_early = chk(C.FIELD_LOW_CONFIDENCE, severity=Severity.medium, route=Route.ap_clerk,
                    stage=StageName.validate_document, rule_id="D03_confidence")  # fmt: skip
    med_late = chk(C.PO_INFERRED, severity=Severity.medium, route=Route.ap_clerk,
                   stage=StageName.resolve_po, rule_id="P02_inference")  # fmt: skip
    d = _decide([med_late, med_early, high_late])
    assert d.reasons == [C.QTY_EXCEEDS_PO_REMAINING, C.FIELD_LOW_CONFIDENCE, C.PO_INFERRED]
    assert d.route == Route.buyer
    same = sorted([chk(C.AMOUNT_VARIANCE_OVER_TOL, rule_id="M03_header"), HOLD], key=order_key)
    assert [c.rule_id for c in same] == ["M02_unit_price", "M03_header"]


def test_notes_summary_and_version() -> None:
    d = _decide([PASS, PASS, WARN])
    assert d.notes == ["ROUND_OFF_APPLIED message."]
    assert d.checks_summary == {"pass": 3, "warn": 1, "fail": 0, "skip": 0}  # incl. A01 pass
    assert d.headline == "Approve for payment — 3 checks passed, with notes"
    assert d.policy_version == policy().policy_version and d.version == 1
    assert d.handoff is None


def test_handoff_amount_at_risk_is_max_of_counted_codes() -> None:
    a = chk(C.QTY_EXCEEDS_PO_REMAINING, severity=Severity.high, at_risk="17110.00")
    b = chk(C.QTY_EXCEEDS_RECEIVED, route=Route.receiving, at_risk="34220.00",
            rule_id="M05_received")  # fmt: skip
    c = chk(C.MATH_TOTAL_MISMATCH, at_risk="99999.00", stage=StageName.validate_document,
            rule_id="D06_total")  # fmt: skip
    d = _decide([a, b, c])
    assert d.handoff is not None and d.handoff.amount_at_risk == Decimal("34220.00")
    assert d.handoff.blocking_codes[0] == C.QTY_EXCEEDS_PO_REMAINING


def test_same_inputs_same_decision() -> None:
    assert _decide([HOLD, WARN]) == _decide([HOLD, WARN])


def test_posting_only_on_approve() -> None:
    ctx = make_ctx()
    ok = decide([PASS], ctx.extraction, policy(), ctx=ctx, decided_at=AT, polish=False)
    assert ok.posting is not None
    held = decide([HOLD], ctx.extraction, policy(), ctx=ctx, decided_at=AT, polish=False)
    assert held.posting is None


def _with_rules(ex: InvoiceExtraction) -> Decision:
    ctx = make_ctx(ex)
    checks = flatten(run_all(ctx))
    return evaluate(checks, ex, policy(), ctx=ctx, decided_at=AT, polish=False).decision


def test_approve_always_carries_a_posting() -> None:
    d = _with_rules(make_extraction())
    assert d.outcome == Outcome.APPROVE and d.posting is not None
    assert sum(ln.taxable_amount + ln.tax_amount for ln in d.posting.lines) == d.posting.total


def test_unread_line_amounts_hold_instead_of_approving_without_posting() -> None:
    """Regression: an S01-like invoice with unread line amounts auto-approved with
    posting=null."""
    lines = [dict(S01_LINES[0], amount=None), dict(S01_LINES[1], amount=None)]
    d = _with_rules(make_extraction(line_items=lines))
    assert (d.outcome, d.route, d.final) == (Outcome.HOLD, Route.ap_clerk, False)
    assert d.primary_reason == C.POSTING_INCOMPLETE and d.posting is None
    assert d.handoff is not None and "couldn't be read" in d.handoff.question
    assert d.headline == "Hold — Can't build the posting"
