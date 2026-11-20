"""Turn check results into a decision (RULES §3). Pure: same inputs, same decision."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app import clock
from app.config import get_settings
from app.enums import CheckStatus, Outcome, ReasonCode, Route, Severity, StageName
from app.llm.base import LLMClient
from app.models.checks import CheckResult
from app.models.decision import Decision, PostingPayload
from app.models.extraction import InvoiceExtraction
from app.rules import matching
from app.rules.base import Emitter, RuleContext, decimal_value, inr
from app.rules.registry import STAGES, flatten, run_all

from .explain import explain
from .handoff import Facts, build_handoff
from .messages import internal_note, vendor_email
from .policy import Policy
from .posting import posting_for

A01 = Emitter("A01_approval_limit", StageName.decide)
A02 = Emitter("A02_posting_ready", StageName.decide)

SEVERITY_RANK = {
    Severity.critical: 0,
    Severity.high: 1,
    Severity.medium: 2,
    Severity.low: 3,
    Severity.info: 4,
}
STAGE_ORDER = {s: i for i, s in enumerate([*STAGES, StageName.decide])}


def is_active(c: CheckResult) -> bool:
    """A failing check that review hasn't resolved."""
    return c.status == CheckStatus.fail and not c.resolved_by_review


def outcome_before_limit(active: list[CheckResult]) -> Outcome | None:
    if any(c.outcome_hint == Outcome.REJECT for c in active):
        return Outcome.REJECT
    if any(c.severity == Severity.critical for c in active):
        return Outcome.HOLD
    if any(c.outcome_hint == Outcome.RETURN for c in active):
        return Outcome.RETURN
    if active:
        return Outcome.HOLD
    return None


def approval_check(
    checks: list[CheckResult], extraction: InvoiceExtraction, policy: Policy
) -> CheckResult:
    """A01: only when the outcome would otherwise be APPROVE."""
    limit = policy.approval.auto_approve_limit
    if outcome_before_limit([c for c in checks if is_active(c)]) is not None:
        return A01.skip(
            "Auto-approval limit", "Not applicable: the invoice isn't otherwise approvable."
        )
    total = decimal_value(extraction.total)
    if total is not None and total > limit:
        return A01.fail(
            ReasonCode.APPROVAL_LIMIT_EXCEEDED,
            "Above the auto-approval limit",
            f"Everything matches, but the total {inr(total)} is above the {inr(limit)} "
            "auto-approval limit, so the finance controller must approve it.",
            severity=Severity.medium,
            route=Route.controller,
            hint=Outcome.HOLD,
            evidence={"total": str(total), "limit": str(limit)},
        )
    return A01.passed("Within the auto-approval limit", f"{inr(total)} is within {inr(limit)}.")


def posting_check(
    checks: list[CheckResult], extraction: InvoiceExtraction, ctx: RuleContext
) -> tuple[CheckResult, PostingPayload | None]:
    """A02: an otherwise approvable invoice must yield a complete posting payload whose lines
    add up to the total; if it can't, hold it for AP instead of approving without one."""
    if outcome_before_limit([c for c in checks if is_active(c)]) is not None:
        return A02.skip(
            "Posting ready", "Not applicable: the invoice isn't otherwise approvable."
        ), None
    result = posting_for(extraction, ctx.vendor, ctx.po, matching.build_view(ctx))
    if result.posting is None:
        gaps = "; ".join(result.gaps)
        return A02.fail(
            ReasonCode.POSTING_INCOMPLETE,
            "Can't build the posting",
            f"The checks pass, but the invoice can't be posted: {gaps}. Correct the fields "
            "from the document before approving.",
            severity=Severity.medium,
            route=Route.ap_clerk,
            hint=Outcome.HOLD,
            evidence={"gaps": result.gaps},
        ), None
    p = result.posting
    n = len(p.lines)
    return A02.passed(
        "Posting ready",
        f"{n} posting line{'s' if n != 1 else ''} adding up to {inr(p.total)}.",
    ), p


# Follow-up a reviewer's resolution leaves behind, shown as a note on the decision.
FOLLOW_UP = {
    ReasonCode.BANK_DETAILS_CHANGED: (
        "Bank details confirmed by call-back: update vendor master via change control before "
        "the payment run. Payment goes to the account on file."
    ),
}


def follow_ups(checks: list[CheckResult]) -> list[str]:
    return [
        FOLLOW_UP[c.code]
        for c in checks
        if c.status == CheckStatus.fail and c.resolved_by_review and c.code in FOLLOW_UP
    ]


def group_rank(c: CheckResult) -> int:
    if c.status == CheckStatus.warn:
        return 5
    if c.rule_id == A01.rule_id:
        return 4
    if c.outcome_hint == Outcome.REJECT:
        return 0
    if c.severity == Severity.critical:
        return 1
    if c.outcome_hint == Outcome.RETURN:
        return 2
    return 3


def order_key(c: CheckResult) -> tuple[int, int, int, str]:
    return (group_rank(c), SEVERITY_RANK[c.severity], STAGE_ORDER.get(c.stage, 99), c.rule_id)


@dataclass(frozen=True)
class DecisionResult:
    decision: Decision
    checks: list[CheckResult]  # the input checks plus the A02 and A01 results
    llm_calls: list[dict[str, Any]] = field(default_factory=list)  # polish call, for the log


def evaluate(
    checks: list[CheckResult],
    extraction: InvoiceExtraction,
    policy: Policy,
    version_no: int = 1,
    *,
    ctx: RuleContext | None = None,
    decided_at: datetime | None = None,
    client: LLMClient | None = None,
    polish: bool | None = None,
) -> DecisionResult:
    checks = [c for c in checks if c.stage != StageName.decide]
    posting = None
    if ctx is not None:
        a02, posting = posting_check(checks, extraction, ctx)
        checks.append(a02)
    checks = [*checks, approval_check(checks, extraction, policy)]
    active = sorted((c for c in checks if is_active(c)), key=order_key)
    warnings = sorted(
        (c for c in checks if c.status == CheckStatus.warn and not c.resolved_by_review),
        key=order_key,
    )
    outcome = outcome_before_limit(active)
    if outcome is None:
        outcome = Outcome.HOLD if active else Outcome.APPROVE
    ordered = active + warnings
    reasons = list(dict.fromkeys(c.code for c in ordered if c.code is not None))
    primary_check = ordered[0] if ordered else None
    primary_fail = active[0] if active else None

    if outcome in (Outcome.APPROVE, Outcome.REJECT):
        route = Route.none
    elif outcome == Outcome.RETURN:
        route = Route.vendor
    else:
        route = primary_fail.route if primary_fail else Route.none

    passed = sum(1 for c in checks if c.status == CheckStatus.pass_)
    if outcome == Outcome.APPROVE:
        headline = f"Approve for payment — {passed} checks passed" + (
            ", with notes" if warnings else ""
        )
    else:
        label = {Outcome.HOLD: "Hold", Outcome.RETURN: "Return to vendor", Outcome.REJECT: "Reject"}
        headline = f"{label[outcome]} — {primary_fail.title if primary_fail else ''}"

    facts = Facts.build(extraction, ctx, policy.approval.auto_approve_limit)
    handoff = None
    vendor_message = note = None
    if primary_fail is not None:
        handoff_primary = _handoff_primary(active, outcome)
        plan = build_handoff(handoff_primary, active, facts, route)
        handoff = plan.handoff
        vendor_message = vendor_email(plan, facts, outcome, active)
        note = internal_note(plan, facts)

    if outcome != Outcome.APPROVE:
        posting = None

    calls: list[dict[str, Any]] = []
    explanation = explain(
        outcome,
        route,
        primary_fail,
        checks,
        facts,
        vendor_message=vendor_message,
        internal_note=note,
        client=client,
        polish=get_settings().llm_explain if polish is None else polish,
        calls=calls,
    )
    summary = {s.value: 0 for s in CheckStatus}
    for c in checks:
        summary[c.status.value] += 1
    decision = Decision(
        version=version_no,
        outcome=outcome,
        route=route,
        headline=headline,
        primary_reason=primary_check.code if primary_check else None,
        reasons=reasons,
        notes=[c.message for c in warnings] + follow_ups(checks),
        handoff=handoff,
        explanation=explanation,
        posting=posting,
        checks_summary=summary,
        policy_version=policy.policy_version,
        decided_at=decided_at or clock.now(),
        final=outcome in (Outcome.APPROVE, Outcome.REJECT),
    )
    return DecisionResult(decision, checks, calls)


def _handoff_primary(active: list[CheckResult], outcome: Outcome) -> CheckResult:
    """The check the handoff is about: for RETURN, the first one the vendor must fix."""
    if outcome == Outcome.RETURN:
        vendor_side = [c for c in active if c.outcome_hint == Outcome.RETURN]
        if vendor_side:
            return vendor_side[0]
    return active[0]


def decide(
    checks: list[CheckResult],
    extraction: InvoiceExtraction,
    policy: Policy,
    version_no: int = 1,
    **kwargs: object,
) -> Decision:
    return evaluate(checks, extraction, policy, version_no, **kwargs).decision  # type: ignore[arg-type]


def redecide(
    ctx: RuleContext, policy: Policy, version_no: int = 1, **kwargs: object
) -> DecisionResult:
    """Re-run every rule and the decision under another policy, on a copy of a context. The
    copy keeps the context's PO and duplicate candidates, so this only answers tolerance and
    limit what-ifs; `/policy/preview` rebuilds the context under the proposed policy instead."""
    fresh = dataclasses.replace(ctx, policy=policy, cache={})
    checks = flatten(run_all(fresh))
    return evaluate(checks, fresh.extraction, policy, version_no, ctx=fresh, **kwargs)  # type: ignore[arg-type]
