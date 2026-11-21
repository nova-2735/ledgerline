"""Drafts: the vendor email and the internal note (RULES §4). Nothing is sent automatically.

The vendor email always goes to the address in the vendor master, never to one printed on the
invoice, and a changed bank account never produces a vendor email (the call-back must use the
number on file).
"""

from __future__ import annotations

from app.enums import Outcome, ReasonCode, Route
from app.models.checks import CheckResult
from app.models.decision import Message
from app.rules.base import inr

from .handoff import _GENERIC_VENDOR, ROUTE_LABELS, Facts, HandoffPlan, template_values

MAX_WORDS = 120


def _subject(facts: Facts, reason: str) -> str:
    ref = facts.number
    if ref is None and facts.invoice_date is not None:
        ref = f"dated {facts.invoice_date:%d %b %Y}"
    return f"Invoice {ref or '(no number)'} — action needed ({reason})"


def _opening(facts: Facts) -> str:
    what = f"invoice {facts.number}" if facts.number else "your invoice"
    when = f" dated {facts.invoice_date:%d %b %Y}" if facts.invoice_date else ""
    return f"Thank you for {what}{when} for {inr(facts.total)}."


def _trim(text: str) -> str:
    words = text.split(" ")
    if len(words) <= MAX_WORDS:
        return text
    return " ".join(words[:MAX_WORDS]).rstrip(",;") + "…"


def vendor_email(
    plan: HandoffPlan, facts: Facts, outcome: Outcome, active: list[CheckResult]
) -> Message | None:
    if facts.vendor is None:
        return None
    if any(c.code == ReasonCode.BANK_DETAILS_CHANGED for c in active):
        return None
    t = plan.template
    values = plan.values
    if t.draft != "vendor":
        if outcome != Outcome.RETURN:
            return None
        primary_vendor = next((c for c in active if c.route == Route.vendor), None)
        if primary_vendor is None:
            return None
        t = _GENERIC_VENDOR
        values = template_values(primary_vendor, facts, active)
    ask = t.vendor_ask.format_map(values)
    body = (
        f"Dear {facts.vendor.legal_name} team,\n\n{_opening(facts)} {ask}\n\n"
        f"Regards,\nAccounts Payable, {facts.company_name}"
    )
    return Message(
        to=facts.vendor.email,
        subject=_subject(facts, t.short_reason),
        body=_trim(body),
        channel="email",
    )


def internal_note(plan: HandoffPlan, facts: Facts) -> Message | None:
    t = plan.template
    if t.draft != "internal" or t.internal_to is None:
        return None
    owner = t.internal_to
    to = ROUTE_LABELS[owner].capitalize()
    if owner == Route.buyer and facts.po is not None:
        to = f"Buyer — {facts.po.buyer_name}"
    elif owner == Route.buyer and facts.vendor is None:
        to = "Procurement"
    h = plan.handoff
    risk = (
        f" Amount at risk: {inr(h.amount_at_risk)}."
        if h.amount_at_risk is not None
        else f" Invoice total: {inr(facts.total)}."
    )
    body = f"{h.question}\n\nSuggested: {h.suggested_action}{risk}"
    return Message(
        to=to,
        subject=f"Invoice {facts.number or '(no number)'} from {facts.vendor_name}: please review",
        body=body,
        channel="internal",
    )
