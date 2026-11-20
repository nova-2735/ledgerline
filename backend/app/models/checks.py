"""Check results and the line-matching view."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import model_validator

from app.enums import CheckStatus, MatchType, Outcome, ReasonCode, Route, Severity, StageName
from app.models.common import Dec, Model, Money


class CheckResult(Model):
    rule_id: str
    stage: StageName
    status: CheckStatus
    code: ReasonCode | None
    severity: Severity
    title: str
    message: str
    evidence: dict[str, Any]
    route: Route
    outcome_hint: Outcome | None
    amount_at_risk: Money | None
    resolved_by_review: bool = False

    @model_validator(mode="after")
    def _code_required_when_not_passing(self) -> Self:
        if self.status in (CheckStatus.warn, CheckStatus.fail) and self.code is None:
            raise ValueError("code is required when status is warn or fail")
        return self


class POCandidate(Model):
    po_number: str
    score: float
    components: dict[str, float]
    reason: str


class MatchRow(Model):
    invoice_line_indexes: list[int]
    po_line_nos: list[int]
    kind: Literal["one_to_one", "bundled", "unmatched_invoice", "unmatched_po"]
    description_invoice: str | None
    description_po: str | None
    similarity: float | None
    qty_invoiced: Dec | None
    qty_ordered: Dec | None
    qty_received: Dec | None
    qty_billed_before: Dec | None
    qty_available: Dec | None
    unit_price_invoice: Money | None
    unit_price_po: Money | None
    price_variance_pct: Dec | None
    amount_invoice: Money | None
    amount_expected: Money | None
    status: CheckStatus
    codes: list[ReasonCode]
    matched_by: Literal["code", "fuzzy", "bundle", "llm"]


class MatchingView(Model):
    po_number: str | None
    match_type: MatchType | None
    rows: list[MatchRow]
    header_expected: Money | None
    header_invoiced: Money | None
    header_variance: Money | None
    po_candidates: list[POCandidate]
