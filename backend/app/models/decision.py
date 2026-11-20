"""Decision, handoff, explanation and posting payload."""

from __future__ import annotations

from datetime import date
from typing import Literal

from app.enums import ActionType, Outcome, ReasonCode, Route
from app.models.common import Model, Money, UtcDatetime


class Handoff(Model):
    owner: Route
    question: str
    suggested_action: str
    actions: list[ActionType]
    amount_at_risk: Money | None
    blocking_codes: list[ReasonCode]


class Message(Model):
    to: str
    subject: str
    body: str
    channel: Literal["email", "internal"]


class Explanation(Model):
    summary: str
    bullets: list[str]
    generated_by: Literal["template", "llm"]
    model: str | None
    vendor_message: Message | None
    internal_note: Message | None


class PostingLine(Model):
    po_number: str
    po_line_no: int
    gl_account: str
    cost_center: str
    taxable_amount: Money
    tax_amount: Money
    description: str


class PostingPayload(Model):
    vendor_id: str
    invoice_number: str
    invoice_date: date
    due_date: date
    currency: str
    lines: list[PostingLine]
    total: Money
    payment_terms_days: int
    remit_to: dict[str, str]


class Decision(Model):
    version: int
    outcome: Outcome
    route: Route
    headline: str
    primary_reason: ReasonCode | None
    reasons: list[ReasonCode]
    notes: list[str]
    handoff: Handoff | None
    explanation: Explanation
    posting: PostingPayload | None
    checks_summary: dict[str, int]
    policy_version: str
    decided_at: UtcDatetime
    final: bool
