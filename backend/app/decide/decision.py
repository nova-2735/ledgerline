"""Turn check results into a decision (RULES §3). Pure: same inputs, same decision."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime

from app import clock
from app.config import get_settings
from app.enums import CheckStatus, Outcome, ReasonCode, Route, Severity, StageName
from app.llm.base import LLMClient
from app.models.checks import CheckResult
from app.models.decision import Decision
from app.models.extraction import InvoiceExtraction
from app.rules import matching
from app.rules.base import Emitter, RuleContext, decimal_value, inr
from app.rules.registry import STAGES, flatten, run_all

from .explain import explain
from .handoff import Facts, build_handoff
from .messages import internal_note, vendor_email
from .policy import Policy
from .posting import build_posting

A01 = Emitter("A01_approval_limit", StageName.decide)

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
    checks: list[CheckResult]  # the input checks plus the A01 result


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

    posting = None
    if outcome == Outcome.APPROVE and ctx is not None:
        posting = build_posting(extraction, ctx.vendor, ctx.po, matching.build_view(ctx))

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
        notes=[c.message for c in warnings],
        handoff=handoff,
        explanation=explanation,
        posting=posting,
        checks_summary=summary,
        policy_version=policy.policy_version,
        decided_at=decided_at or clock.now(),
        final=outcome in (Outcome.APPROVE, Outcome.REJECT),
    )
    return DecisionResult(decision, checks)


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
    """Re-run every rule and the decision under another policy, on a copy of a stored run's
    context (for `/policy/preview`). Nothing is persisted."""
    fresh = dataclasses.replace(ctx, policy=policy, cache={})
    checks = flatten(run_all(fresh))
    return evaluate(checks, fresh.extraction, policy, version_no, ctx=fresh, **kwargs)  # type: ignore[arg-type]
