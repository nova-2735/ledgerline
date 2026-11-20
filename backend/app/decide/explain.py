"""Explanation: a template summary and bullets, optionally polished by the model.

The polish is accepted only when every number in the template summary survives and the outcome
word is still there; otherwise the template stands (`generated_by="template"`).
"""

from __future__ import annotations

from typing import Any

from app.enums import CheckStatus, Outcome, Route
from app.llm.base import LLMClient, LLMError, polish_is_safe
from app.models.checks import CheckResult
from app.models.decision import Explanation, Message
from app.rules.base import inr

from .handoff import ROUTE_LABELS, Facts

OUTCOME_WORDS = {
    Outcome.APPROVE: "approv",
    Outcome.HOLD: "hold",
    Outcome.RETURN: "return",
    Outcome.REJECT: "reject",
}


def _what(facts: Facts) -> str:
    number = f" {facts.number}" if facts.number else ""
    po = f" against {facts.po.po_number}" if facts.po else ""
    return f"{facts.vendor_name} invoice{number} for {inr(facts.total)}{po}"


def template_summary(
    outcome: Outcome,
    route: Route,
    primary: CheckResult | None,
    checks: list[CheckResult],
    facts: Facts,
) -> str:
    passed = sum(1 for c in checks if c.status == CheckStatus.pass_)
    counted = sum(1 for c in checks if c.status != CheckStatus.skip)
    notes = sum(1 for c in checks if c.status == CheckStatus.warn and not c.resolved_by_review)
    if outcome == Outcome.APPROVE:
        with_notes = f", with {notes} note{'s' if notes != 1 else ''}" if notes else ""
        return f"Approve for payment: {_what(facts)}. {passed} checks passed{with_notes}."
    reason = primary.message if primary else ""
    tally = f"{passed} of {counted} checks passed."
    if outcome == Outcome.HOLD:
        return f"Hold for the {ROUTE_LABELS[route]}: {_what(facts)}. {reason} {tally}"
    if outcome == Outcome.RETURN:
        return f"Return to vendor: {_what(facts)}. {reason} {tally}"
    return f"Reject: {_what(facts)}. {reason} {tally}"


def bullets(checks: list[CheckResult]) -> list[str]:
    failing = [
        c.message for c in checks if c.status == CheckStatus.fail and not c.resolved_by_review
    ]
    warnings = [
        c.message for c in checks if c.status == CheckStatus.warn and not c.resolved_by_review
    ]
    resolved = [c.message for c in checks if c.resolved_by_review]
    return failing + warnings + resolved


def polish_accepted(original: str, rewritten: str, outcome: Outcome) -> bool:
    """All template numbers kept, still short, and the outcome word still present."""
    if rewritten.strip() == original.strip():
        return False
    return polish_is_safe(original, rewritten) and OUTCOME_WORDS[outcome] in rewritten.lower()


def explain(
    outcome: Outcome,
    route: Route,
    primary: CheckResult | None,
    checks: list[CheckResult],
    facts: Facts,
    *,
    vendor_message: Message | None,
    internal_note: Message | None,
    client: LLMClient | None = None,
    polish: bool = False,
) -> Explanation:
    summary = template_summary(outcome, route, primary, checks, facts)
    generated_by: Any = "template"
    model = None
    if polish and client is not None and client.is_live:
        info = {
            "outcome": outcome.value,
            "route": route.value,
            "primary_reason": primary.code.value if primary and primary.code else None,
            "total": str(facts.total) if facts.total is not None else None,
        }
        try:
            rewritten = client.polish(summary, info)
        except LLMError:
            rewritten = summary
        if polish_accepted(summary, rewritten, outcome):
            summary, generated_by, model = rewritten.strip(), "llm", client.model_light
    return Explanation(
        summary=summary,
        bullets=bullets(checks),
        generated_by=generated_by,
        model=model,
        vendor_message=vendor_message,
        internal_note=internal_note,
    )
