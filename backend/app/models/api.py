"""Request and response bodies for the HTTP API (CONTRACTS §5)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from app.enums import ActionType, Outcome, ReasonCode, Route
from app.models.common import Dec, Model, Money, UtcDatetime
from app.models.reference import GoodsReceipt, POLineBalance, PurchaseOrder, Vendor
from app.models.run import RunDetail, RunEvent, RunSummary


class ErrorResponse(Model):
    detail: str
    code: str


class HealthResponse(Model):
    status: str
    version: str
    app_env: str
    llm_provider: str
    llm_model: str
    llm_model_light: str
    ocr_available: bool
    db: str
    today: dt.date


class RunCreated(Model):
    run_id: int


class DemoRunRequest(Model):
    force_fresh: bool = False


class DemoInboxItem(Model):
    doc_id: str
    sender_name: str
    sender_email: str
    subject: str
    received_at: UtcDatetime
    filename: str
    title: str
    tags: list[str]
    is_edge_case: bool
    processed_run_ids: list[int]
    group: Literal["scenario", "stress"] = Field(
        default="scenario",
        description="scenario: the 15 demo scenarios; stress: unseen out-of-distribution files",
    )


class ResetResponse(Model):
    status: Literal["ok"]
    runs: int
    mode: Literal["snapshot", "reseed"] = Field(
        description="snapshot: the seeded database was restored; reseed: rebuilt via the pipeline"
    )
    duration_ms: int


class RunList(Model):
    items: list[RunSummary]
    total: int


class AuditExport(Model):
    run: RunDetail
    events: list[RunEvent]
    raw_model_output: dict[str, Any] | None


class ReviewRequest(Model):
    action: ActionType
    reviewer: str
    note: str
    po_number: str | None = None
    field_corrections: dict[str, str] | None = None
    fields_verified: bool | None = None


class QueueItem(RunSummary):
    question: str
    age_hours: float
    amount_at_risk: Money | None


class QueueResponse(Model):
    counts: dict[str, int]
    items: list[QueueItem]


class VendorOut(Vendor):
    open_po_count: int
    invoice_count: int


class PurchaseOrderOut(PurchaseOrder):
    ordered_value: Money
    billed_value: Money
    pct_billed: Dec


class PurchaseOrderDetail(Model):
    po: PurchaseOrder
    balances: list[POLineBalance]
    grns: list[GoodsReceipt]
    runs: list[RunSummary]


class PolicyResponse(Model):
    version: str
    path: str
    policy: dict[str, Any]


class PolicyPreviewRequest(Model):
    overrides: dict[str, Any]
    limit: int = Field(default=50, gt=0, le=500)


class PolicyPreviewChange(Model):
    run_id: int
    display_id: str
    before: Outcome
    after: Outcome
    reasons_before: list[ReasonCode]
    reasons_after: list[ReasonCode]


class PolicyPreviewResponse(Model):
    changed: list[PolicyPreviewChange]
    unchanged: int


class PolicyUpdateRequest(Model):
    overrides: dict[str, Any]


class PolicyVersionResponse(Model):
    version: str


class StatsKpis(Model):
    processed: int
    value_processed: Money
    touchless_rate: float
    awaiting_review: int
    median_decision_ms: int | None
    exposure_stopped: Money


class StatsDay(Model):
    date: dt.date
    APPROVE: int
    HOLD: int
    RETURN: int
    REJECT: int


class StatsReason(Model):
    code: ReasonCode
    count: int
    amount: Money


class StatsRoute(Model):
    route: Route
    count: int


class StatsResponse(Model):
    kpis: StatsKpis
    by_day: list[StatsDay]
    by_reason: list[StatsReason]
    by_route: list[StatsRoute]
