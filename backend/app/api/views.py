"""Build API views of runs from ORM rows."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import DocKind, Outcome, ReasonCode, Route, RunSource, RunStatus
from app.models.checks import CheckResult, MatchingView
from app.models.decision import Decision
from app.models.extraction import InvoiceExtraction
from app.models.run import RunDetail, RunSummary, StageState
from app.orm import RunRow, VendorRow
from app.pipeline.review import approval_block
from app.pipeline.review import to_model as review_model


def vendor_names(session: Session) -> dict[str, str]:
    return dict(session.execute(select(VendorRow.vendor_id, VendorRow.legal_name)).all())


def duration_ms(run: RunRow) -> int | None:
    stages = [s.get("duration_ms") for s in run.stages or []]
    done = [d for d in stages if isinstance(d, int)]
    return sum(done) if done else None


def run_summary(run: RunRow, names: dict[str, str]) -> RunSummary:
    ex = run.extraction or {}
    supplier = (ex.get("supplier_name") or {}).get("value") if ex else None
    vendor_name = names.get(run.vendor_id) if run.vendor_id else None
    return RunSummary(
        id=run.id,
        display_id=run.display_id,
        created_at=run.created_at,
        source=RunSource(run.source),
        filename=run.document.filename,
        scenario_id=run.scenario_id,
        sender_name=run.sender_name,
        sender_email=run.sender_email,
        subject=run.subject,
        status=RunStatus(run.status),
        vendor_id=run.vendor_id,
        vendor_name=vendor_name or (supplier if isinstance(supplier, str) else None),
        invoice_number=run.invoice_number,
        invoice_date=run.invoice_date,
        total=run.total,
        po_number=run.po_number,
        outcome=Outcome(run.outcome) if run.outcome else None,
        route=Route(run.route) if run.route else None,
        primary_reason=ReasonCode(run.primary_reason) if run.primary_reason else None,
        final_outcome=Outcome(run.final_outcome) if run.final_outcome else None,
        duration_ms=duration_ms(run),
        doc_kind=DocKind(ex["doc_kind"]) if ex.get("doc_kind") else None,
        cached_extraction=run.cached_extraction,
    )


def run_detail(session: Session, run: RunRow) -> RunDetail:
    summary = run_summary(run, vendor_names(session))
    return RunDetail(
        **summary.model_dump(),
        stages=[StageState.model_validate(s) for s in run.stages or []],
        checks=[CheckResult.model_validate(c) for c in run.checks or []],
        extraction=InvoiceExtraction.model_validate(run.extraction) if run.extraction else None,
        decision=Decision.model_validate(run.decision) if run.decision else None,
        decision_history=[Decision.model_validate(d) for d in run.decision_history or []],
        review_actions=[review_model(a) for a in run.review_actions],
        page_count=run.document.page_count,
        file_sha256=run.document.sha256,
        matching=MatchingView.model_validate(run.matching) if run.matching else None,
        policy_version=run.policy_version,
        approval_block=approval_block(session, run),
    )
