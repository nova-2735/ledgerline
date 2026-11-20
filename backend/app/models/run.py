"""Runs, stages, events and review actions."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from app.enums import (
    ActionType,
    DocKind,
    Outcome,
    ReasonCode,
    Route,
    RunSource,
    RunStatus,
    StageName,
    StageStatus,
)
from app.models.checks import CheckResult, MatchingView
from app.models.common import Model, Money, UtcDatetime
from app.models.decision import Decision
from app.models.extraction import InvoiceExtraction

EventType = Literal[
    "run.created",
    "run.started",
    "stage.started",
    "stage.log",
    "stage.completed",
    "decision.made",
    "run.awaiting_review",
    "run.completed",
    "run.failed",
    "review.recorded",
    "run.resumed",
]


class StageState(Model):
    name: StageName
    status: StageStatus
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    duration_ms: int | None
    summary: str | None
    check_rule_ids: list[str]
    detail: dict[str, Any]


class ReviewAction(Model):
    id: int
    run_id: int
    action: ActionType
    reviewer: str
    note: str
    po_number: str | None
    field_corrections: dict[str, str] | None
    fields_verified: bool | None
    created_at: UtcDatetime
    resulting_decision_version: int | None


class RunSummary(Model):
    id: int
    display_id: str
    created_at: UtcDatetime
    source: RunSource
    filename: str
    scenario_id: str | None
    sender_name: str | None
    sender_email: str | None
    subject: str | None
    status: RunStatus
    vendor_id: str | None
    vendor_name: str | None
    invoice_number: str | None
    invoice_date: date | None
    total: Money | None
    po_number: str | None
    outcome: Outcome | None
    route: Route | None
    primary_reason: ReasonCode | None
    final_outcome: Outcome | None
    duration_ms: int | None
    doc_kind: DocKind | None
    cached_extraction: bool


class RunDetail(RunSummary):
    stages: list[StageState]
    checks: list[CheckResult]
    extraction: InvoiceExtraction | None
    decision: Decision | None
    decision_history: list[Decision]
    review_actions: list[ReviewAction]
    page_count: int
    file_sha256: str
    matching: MatchingView | None
    policy_version: str | None
    approval_block: str | None  # why approve would be refused now; None when it's allowed


class RunEvent(Model):
    seq: int
    run_id: int
    ts: UtcDatetime
    type: EventType
    stage: StageName | None
    status: StageStatus | None
    message: str | None
    data: dict[str, Any] | None
