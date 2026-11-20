"""Reviewer actions (CONTRACTS §4.7): finalise a run, or record an override and resume it.

- approve / reject / send_to_vendor finalise: a new decision version records the reviewer's call.
  Approve is refused (409) while a critical, FIELD_MISSING_* or POSTING_INCOMPLETE check is
  unresolved, or when no complete posting payload can be built (RULES §3).
- confirm_po / verify_bank / not_duplicate resume from `resolve_po`; correct_fields / reopen
  resume from `validate_document`. The rules then decide again (a new decision version).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import clock
from app.db import get_sessionmaker
from app.decide.decision import is_active
from app.decide.posting import PostingResult, posting_for
from app.enums import ActionType, Outcome, ReasonCode, Route, RunStatus, Severity, StageName
from app.llm.base import LLMClient
from app.models.api import ReviewRequest
from app.models.checks import CheckResult, MatchingView
from app.models.decision import Decision, PostingPayload
from app.models.extraction import InvoiceExtraction
from app.models.run import ReviewAction
from app.orm import ReviewActionRow, RunRow
from app.reference.purchase_orders import get_po
from app.reference.vendors import get_vendor
from app.rules.base import Resolution, ReviewOverrides, text_value

from . import runner
from .events import emit
from .stages import CORRECTABLE_FIELDS

FINAL_OUTCOME = {
    ActionType.approve: Outcome.APPROVE,
    ActionType.reject: Outcome.REJECT,
    ActionType.send_to_vendor: Outcome.RETURN,
}
RESUME_FROM = {
    ActionType.confirm_po: StageName.resolve_po,
    ActionType.verify_bank: StageName.resolve_po,
    ActionType.not_duplicate: StageName.resolve_po,
    ActionType.correct_fields: StageName.validate_document,
    ActionType.reopen: StageName.validate_document,
}
# Actions allowed on a run that has already been finalised (e.g. an automatic duplicate REJECT).
ON_COMPLETED = frozenset({ActionType.not_duplicate, ActionType.reopen})
ACTION_LABEL = {
    ActionType.approve: "Approval",
    ActionType.reject: "Rejection",
    ActionType.send_to_vendor: "Return to vendor",
    ActionType.confirm_po: "PO confirmation",
    ActionType.verify_bank: "Bank call-back",
    ActionType.correct_fields: "Field check",
    ActionType.not_duplicate: "Not-a-duplicate",
    ActionType.reopen: "Reopen",
}
# Approve is refused while one of these is unresolved: a final APPROVE needs these fields.
FIELD_MISSING = frozenset(
    {
        ReasonCode.FIELD_MISSING_INVOICE_NUMBER,
        ReasonCode.FIELD_MISSING_INVOICE_DATE,
        ReasonCode.FIELD_MISSING_TOTAL,
        ReasonCode.FIELD_MISSING_SUPPLIER,
    }
)
VERB = {
    Outcome.APPROVE: "Approved",
    Outcome.REJECT: "Rejected",
    Outcome.RETURN: "Returned to vendor",
}


@dataclass
class ReviewError(Exception):
    status_code: int
    code: str
    detail: str


def to_model(row: ReviewActionRow) -> ReviewAction:
    return ReviewAction(
        id=row.id,
        run_id=row.run_id,
        action=ActionType(row.action),
        reviewer=row.reviewer,
        note=row.note,
        po_number=row.po_number,
        field_corrections=row.field_corrections,
        fields_verified=row.fields_verified,
        created_at=row.created_at,
        resulting_decision_version=row.resulting_decision_version,
    )


def _validate(req: ReviewRequest) -> None:
    if not req.reviewer.strip():
        raise ReviewError(422, "reviewer_required", "Please give your name.")
    if not req.note.strip():
        raise ReviewError(422, "note_required", "Please add a short note explaining the action.")
    if req.action == ActionType.confirm_po and not (req.po_number or "").strip():
        raise ReviewError(422, "po_required", "Choose the purchase order to confirm.")
    if req.action == ActionType.correct_fields:
        corrections = req.field_corrections or {}
        unknown = sorted(set(corrections) - CORRECTABLE_FIELDS)
        if unknown:
            raise ReviewError(
                422, "unknown_field", f"These fields can't be corrected: {', '.join(unknown)}."
            )
        if not corrections and not req.fields_verified:
            raise ReviewError(
                422,
                "nothing_to_correct",
                "Give the corrected values, or confirm the highlighted values are right.",
            )


def _check_status(run: RunRow, action: ActionType) -> None:
    status = RunStatus(run.status)
    if status == RunStatus.awaiting_review:
        return
    if status == RunStatus.completed and action in ON_COMPLETED:
        return
    if status in (RunStatus.queued, RunStatus.running):
        raise ReviewError(409, "run_busy", "This invoice is still being processed.")
    raise ReviewError(
        409, "not_awaiting_review", f"This invoice is {status.value.replace('_', ' ')}."
    )


def _resolution(req: ReviewRequest) -> Resolution:
    return Resolution(reviewer=req.reviewer.strip(), note=req.note.strip())


def _apply_overrides(overrides: ReviewOverrides, req: ReviewRequest) -> ReviewOverrides:
    res = _resolution(req)
    data = overrides.model_copy(deep=True)
    if req.action == ActionType.confirm_po:
        data.po_number = (req.po_number or "").strip()
        data.resolutions["po_number"] = res
    elif req.action == ActionType.verify_bank:
        data.bank_verified = True
        data.resolutions["bank_verified"] = res
    elif req.action == ActionType.not_duplicate:
        data.not_duplicate = True
        data.resolutions["not_duplicate"] = res
    elif req.action == ActionType.correct_fields:
        data.field_corrections = {**data.field_corrections, **(req.field_corrections or {})}
        data.resolutions["field_corrections"] = res
    if req.fields_verified and req.action in (ActionType.confirm_po, ActionType.correct_fields):
        data.fields_verified = True
        data.resolutions["fields_verified"] = res
    return data


def _posting(session: Session, run: RunRow) -> PostingResult:
    if run.extraction is None:
        return PostingResult(None, ["the invoice hasn't been read"])
    vendor = get_vendor(session, run.vendor_id) if run.vendor_id else None
    po = get_po(session, run.po_number) if run.po_number else None
    return posting_for(
        InvoiceExtraction.model_validate(run.extraction),
        vendor,
        po,
        MatchingView.model_validate(run.matching) if run.matching else None,
    )


def _approvable(session: Session, run: RunRow, checks: list[CheckResult]) -> PostingPayload:
    """The posting an approve would produce; `ReviewError` 409 when approve isn't allowed."""
    active = [c for c in checks if is_active(c)]
    critical = [c for c in active if c.severity == Severity.critical]
    if critical:
        raise ReviewError(
            409,
            "critical_unresolved",
            f"Can't approve while “{critical[0].title}” is unresolved. "
            "Resolve it first (for bank details: call the vendor on the number on file "
            "and record the call-back).",
        )
    missing = [c for c in active if c.code in FIELD_MISSING]
    if missing:
        raise ReviewError(
            409,
            "field_missing",
            f"Can't approve: “{missing[0].title}”. Correct the field from the document, or "
            "return the invoice to the vendor.",
        )
    if run.extraction is not None and run.vendor_id is None:
        supplier = text_value(InvoiceExtraction.model_validate(run.extraction).supplier_name)
        raise ReviewError(
            409,
            "posting_incomplete",
            f"Can't approve: {supplier or 'the supplier'} isn't in the vendor master, so there's "
            "no vendor record to pay. Procurement must onboard the vendor first; until then, "
            "keep the invoice on hold or reject it.",
        )
    result = _posting(session, run)
    blocked = [c for c in active if c.code == ReasonCode.POSTING_INCOMPLETE]
    if blocked or result.posting is None:
        gaps = "; ".join(result.gaps) or (blocked[0].message if blocked else "")
        raise ReviewError(
            409,
            "posting_incomplete",
            f"Can't approve: there's no complete posting for this invoice ({gaps}). "
            "Correct the fields, or return or reject the invoice.",
        )
    return result.posting


def approval_block(session: Session, run: RunRow) -> str | None:
    """Why the review endpoint would refuse `approve` right now; None when it would accept it."""
    if run.decision is None:
        return None
    try:
        _approvable(session, run, [CheckResult.model_validate(c) for c in run.checks or []])
    except ReviewError as exc:
        return exc.detail
    return None


def _human_decision(
    latest: Decision, outcome: Outcome, req: ReviewRequest, posting: PostingPayload | None
) -> Decision:
    """The reviewer's call as a new decision version; reasons and notes are kept for the record."""
    reviewer, note = req.reviewer.strip(), req.note.strip()
    headline = f"{VERB[outcome]} by {reviewer}"
    explanation = latest.explanation.model_copy(
        update={
            "summary": f"{headline}: {note} (The checks had recommended: {latest.headline}.)",
            "vendor_message": None
            if outcome == Outcome.APPROVE
            else latest.explanation.vendor_message,
        }
    )
    return latest.model_copy(
        update={
            "version": latest.version + 1,
            "outcome": outcome,
            "route": Route.vendor if outcome == Outcome.RETURN else Route.none,
            "headline": headline,
            "handoff": None,
            "explanation": explanation,
            "posting": posting if outcome == Outcome.APPROVE else None,
            "decided_at": clock.now(),
            "final": True,
        }
    )


def apply_review(
    run_id: int,
    req: ReviewRequest,
    *,
    background: bool = True,
    client: LLMClient | None = None,
    polish: bool | None = None,
) -> ReviewAction:
    """Record a review action and act on it. Raises `ReviewError` for invalid requests and
    `runner.ResetInProgress` while the demo is being reset."""
    _validate(req)
    with runner.work():
        return _apply(run_id, req, background=background, client=client, polish=polish)


def _apply(
    run_id: int,
    req: ReviewRequest,
    *,
    background: bool,
    client: LLMClient | None,
    polish: bool | None,
) -> ReviewAction:
    with get_sessionmaker()() as session:
        run = session.get(RunRow, run_id)
        if run is None:
            raise ReviewError(404, "run_not_found", f"Run {run_id} not found.")
        _check_status(run, req.action)
        if run.decision is None:
            raise ReviewError(409, "no_decision", "This invoice has no decision to review yet.")
        latest = Decision.model_validate(run.decision)
        checks = [CheckResult.model_validate(c) for c in run.checks or []]
        posting = _approvable(session, run, checks) if req.action == ActionType.approve else None
        if req.action == ActionType.confirm_po and get_po(session, req.po_number or "") is None:
            raise ReviewError(422, "po_not_found", f"There is no purchase order {req.po_number}.")

        row = ReviewActionRow(
            run_id=run_id,
            action=req.action.value,
            reviewer=req.reviewer.strip(),
            note=req.note.strip(),
            po_number=(req.po_number or "").strip() or None,
            field_corrections=req.field_corrections,
            fields_verified=req.fields_verified,
            created_at=clock.now(),
        )
        session.add(row)
        session.flush()
        review = to_model(row)
        review_data = {"review": review.model_dump(mode="json")}

        outcome = FINAL_OUTCOME.get(req.action)
        if outcome is not None:
            if outcome == Outcome.APPROVE:
                note = f" Resolved by {review.reviewer}: {review.note}"
                checks = [
                    c.model_copy(update={"resolved_by_review": True, "message": c.message + note})
                    if is_active(c)
                    else c
                    for c in checks
                ]
                run.checks = [c.model_dump(mode="json") for c in checks]
            decision = _human_decision(latest, outcome, req, posting)
            with runner.ledger_lock:
                runner.record_outcome(session, run, decision)
                session.commit()
            review = to_model(row)
            emit(
                run_id,
                "review.recorded",
                message=f"{ACTION_LABEL[req.action]} recorded",
                data=review_data,
            )
            emit(
                run_id,
                "decision.made",
                message=decision.headline,
                data={
                    "decision": decision.model_dump(mode="json"),
                    "outcome": decision.outcome.value,
                    "route": decision.route.value,
                },
            )
            runner.terminal_event(run, decision)
            return review

        overrides = _apply_overrides(ReviewOverrides.model_validate(run.overrides or {}), req)
        run.overrides = overrides.model_dump(mode="json")
        run.status = RunStatus.queued.value
        session.commit()

    emit(
        run_id, "review.recorded", message=f"{ACTION_LABEL[req.action]} recorded", data=review_data
    )
    from_stage = RESUME_FROM[req.action]
    message = f"Resumed after review by {review.reviewer}"
    if review.po_number:
        message += f" · confirmed {review.po_number}"
    kwargs = {
        "message": message,
        "data": {"review_action_id": review.id},
        "client": client,
        "polish": polish,
    }
    if background:
        runner.schedule(runner.resume, run_id, from_stage, **kwargs)
    else:
        runner.resume(run_id, from_stage, **kwargs)  # type: ignore[arg-type]
    return review
