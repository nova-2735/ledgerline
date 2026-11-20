"""Explanation: a template summary and bullets, optionally polished by the model.

The polish is accepted only when every number in the template summary survives, the outcome word
is still there (not negated) and no other outcome's verb was added; otherwise the template stands
(`generated_by="template"`).
"""

from __future__ import annotations

import re
from typing import Any

from app.enums import CheckStatus, Outcome, Route
from app.llm.base import LLMClient, LLMError, polish_is_safe
from app.llm.prompts import load_prompt
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
# Verbs that name an outcome, matched as word stems ("approve", "approved", "approval" …).
OUTCOME_VERBS = {
    Outcome.APPROVE: re.compile(r"\bapprov\w*|\bpay\b|\bpaid\b", re.IGNORECASE),
    Outcome.HOLD: re.compile(r"\bhold\w*|\bheld\b", re.IGNORECASE),
    Outcome.RETURN: re.compile(r"\breturn\w*|\bsend\s+(?:it\s+)?back\b", re.IGNORECASE),
    Outcome.REJECT: re.compile(r"\breject\w*|\bdecline\w*", re.IGNORECASE),
}
_NEGATED = r"\b(?:not|no|never|don't|do not|doesn't|does not|shouldn't|should not|won't)\s+"


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


def polish_rejection(original: str, rewritten: str, outcome: Outcome) -> str | None:
    """Why a rewrite can't replace the template summary, or None when it can: every template
    number kept, still short, the outcome word present and not negated, and no other outcome's
    verb added (“Do not hold invoice 42. Approve payment.” is not a HOLD summary)."""
    if rewritten.strip() == original.strip():
        return "unchanged"
    if not polish_is_safe(original, rewritten):
        return "dropped a number or ran too long"
    if OUTCOME_WORDS[outcome] not in rewritten.lower():
        return "lost the outcome"
    own = OUTCOME_VERBS[outcome].pattern.replace(r"\b", "")
    if re.search(_NEGATED + rf"(?:\w+\s+)?(?:{own})", rewritten, re.IGNORECASE):
        return "negated the outcome"
    for other, verb in OUTCOME_VERBS.items():
        if other != outcome and len(verb.findall(rewritten)) > len(verb.findall(original)):
            return f"mentions {other.value} instead"
    return None


def polish_accepted(original: str, rewritten: str, outcome: Outcome) -> bool:
    return polish_rejection(original, rewritten, outcome) is None


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
    calls: list[dict[str, Any]] | None = None,
) -> Explanation:
    """`calls` collects the `llm_call` payload of the polish call (accepted or not) for the run
    log."""
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
        prompt = load_prompt("polish_explanation")
        call: dict[str, Any] = {"kind": "polish", "provider": client.provider,
                                "model": client.model_light, "prompt": prompt.ref,
                                "cached": False}  # fmt: skip
        try:
            rewritten, meta = client.polish(summary, info)
            call = meta.event_data("polish")
            rejected = polish_rejection(summary, rewritten, outcome)
        except LLMError as exc:
            rejected = None
            call["error"] = str(exc)
        else:
            if rejected is None:
                summary, generated_by, model = rewritten.strip(), "llm", meta.model
        call["accepted"] = generated_by == "llm"
        if rejected is not None:
            call["rejected_because"] = rejected
        if calls is not None:
            calls.append(call)
    return Explanation(
        summary=summary,
        bullets=bullets(checks),
        generated_by=generated_by,
        model=model,
        vendor_message=vendor_message,
        internal_note=internal_note,
    )
