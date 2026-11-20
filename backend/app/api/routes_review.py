"""Review actions and the review queue."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app import clock
from app.api.deps import DB, ERROR_RESPONSES, APIError
from app.api.views import run_detail, run_summary, vendor_names
from app.enums import Route, RunStatus
from app.models.api import QueueItem, QueueResponse, ReviewRequest
from app.models.decision import Decision
from app.models.run import RunDetail
from app.orm import RunRow
from app.pipeline.review import ReviewError, apply_review

router = APIRouter(tags=["review"], responses=ERROR_RESPONSES)


@router.post("/runs/{run_id}/review", response_model=RunDetail)
def review_run(run_id: int, body: ReviewRequest, db: DB) -> RunDetail:
    try:
        apply_review(run_id, body)
    except ReviewError as exc:
        raise APIError(exc.status_code, exc.code, exc.detail) from exc
    db.expire_all()
    run = db.get(RunRow, run_id)
    assert run is not None
    return run_detail(db, run)


@router.get("/queue", response_model=QueueResponse)
def get_queue(db: DB, route: Route | None = None) -> QueueResponse:
    rows = list(
        db.scalars(
            select(RunRow)
            .where(RunRow.status == RunStatus.awaiting_review.value)
            .order_by(RunRow.created_at)
        )
    )
    counts: dict[str, int] = {}
    for r in rows:
        key = r.route or Route.none.value
        counts[key] = counts.get(key, 0) + 1
    names = vendor_names(db)
    now = clock.now()
    items = []
    for r in rows:
        if route is not None and r.route != route.value:
            continue
        d = Decision.model_validate(r.decision) if r.decision else None
        handoff = d.handoff if d else None
        waiting_since = d.decided_at if d else r.created_at
        items.append(
            QueueItem(
                **run_summary(r, names).model_dump(),
                question=(handoff.question or handoff.suggested_action) if handoff else "",
                age_hours=round(max(0.0, (now - waiting_since).total_seconds()) / 3600, 1),
                amount_at_risk=handoff.amount_at_risk if handoff else None,
            )
        )
    return QueueResponse(counts=counts, items=items)
