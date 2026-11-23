"""Decision policy: view, what-if preview, update."""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter
from sqlalchemy import select

from app import clock
from app.api.deps import DB, ERROR_RESPONSES, APIError
from app.config import get_settings
from app.decide.decision import evaluate
from app.decide.policy import Policy, active_policy, save_overrides
from app.enums import Outcome
from app.models.api import (
    PolicyPreviewChange,
    PolicyPreviewRequest,
    PolicyPreviewResponse,
    PolicyResponse,
    PolicyUpdateRequest,
    PolicyVersionResponse,
)
from app.models.decision import Decision
from app.models.extraction import InvoiceExtraction
from app.orm import RunRow
from app.rules.base import ReviewOverrides, build_context, money_currency
from app.rules.registry import flatten, run_all

router = APIRouter(tags=["policy"], responses=ERROR_RESPONSES)


def _with(policy: Policy, overrides: dict[str, object]) -> Policy:
    try:
        return policy.with_overrides(overrides)
    except ValueError as exc:
        raise APIError(422, "invalid_policy", str(exc)) from exc


@router.get("/policy", response_model=PolicyResponse)
def get_policy() -> PolicyResponse:
    policy = active_policy()
    return PolicyResponse(
        version=policy.policy_version,
        path=get_settings().policy_path.name,
        policy=policy.model_dump(mode="json"),
    )


@router.post("/policy/preview", response_model=PolicyPreviewResponse)
def preview_policy(body: PolicyPreviewRequest, db: DB) -> PolicyPreviewResponse:
    """Re-run rules + decide on the latest runs' stored extractions and review overrides, under the
    current policy and under the proposed one. Each run's own billing is left out of the ledger.
    Nothing is persisted."""
    current = active_policy()
    proposed = _with(current, body.overrides)
    rows = db.scalars(
        select(RunRow)
        .where(RunRow.extraction.is_not(None), RunRow.outcome.is_not(None))
        .order_by(RunRow.created_at.desc(), RunRow.id.desc())
        .limit(body.limit)
    )
    changed: list[PolicyPreviewChange] = []
    unchanged = 0
    for run in rows:
        b = _decide(db, run, current)
        a = _decide(db, run, proposed)
        if a.outcome == b.outcome:
            unchanged += 1
            continue
        changed.append(
            PolicyPreviewChange(
                run_id=run.id,
                display_id=run.display_id,
                before=Outcome(b.outcome),
                after=Outcome(a.outcome),
                reasons_before=b.reasons,
                reasons_after=a.reasons,
            )
        )
    db.rollback()
    return PolicyPreviewResponse(changed=changed, unchanged=unchanged)


def _decide(db: DB, run: RunRow, policy: Policy) -> Decision:
    """Rules + decide for a stored run under `policy`. The context is built under that policy
    too, so PO inference thresholds and the duplicate window apply; the run's own billing is left
    out of the balances and later runs out of the duplicate history."""
    with money_currency():
        return _redecide(db, run, policy)


def _redecide(db: DB, run: RunRow, policy: Policy) -> Decision:
    ctx = build_context(
        db,
        InvoiceExtraction.model_validate(run.extraction),
        policy=policy,
        today=run.created_at.astimezone(clock.IST).date(),
        sender_email=run.sender_email,
        overrides=ReviewOverrides.model_validate(run.overrides or {}),
        file_sha256=run.document.sha256,
        run_id=run.id,
    )
    ctx = dataclasses.replace(
        ctx,
        ledger_rows=[r for r in ctx.ledger_rows if r.run_id < run.id],
        file_rows=[r for r in ctx.file_rows if r.run_id < run.id],
    )
    return evaluate(flatten(run_all(ctx)), ctx.extraction, policy, ctx=ctx, polish=False).decision


@router.put("/policy", response_model=PolicyVersionResponse)
def update_policy(body: PolicyUpdateRequest) -> PolicyVersionResponse:
    _with(active_policy(), body.overrides)
    return PolicyVersionResponse(version=save_overrides(body.overrides).policy_version)
