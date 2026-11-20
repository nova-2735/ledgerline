"""Dashboard statistics."""

from __future__ import annotations

import statistics
from datetime import timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app import clock
from app.api.deps import DB, ERROR_RESPONSES
from app.api.views import duration_ms
from app.enums import CheckStatus, Outcome, ReasonCode, Route, RunSource, RunStatus
from app.models.api import StatsDay, StatsKpis, StatsReason, StatsResponse, StatsRoute
from app.orm import RunRow

router = APIRouter(tags=["stats"], responses=ERROR_RESPONSES)

# RULES §8: codes whose amount_at_risk counts as exposure stopped.
EXPOSURE_CODES = frozenset(
    {
        ReasonCode.DUPLICATE_SAME_FILE,
        ReasonCode.DUPLICATE_SAME_INVOICE,
        ReasonCode.DUPLICATE_SUSPECTED,
        ReasonCode.BANK_DETAILS_CHANGED,
        ReasonCode.VENDOR_NOT_FOUND,
        ReasonCode.VENDOR_BLOCKED,
        ReasonCode.QTY_EXCEEDS_PO_REMAINING,
        ReasonCode.QTY_EXCEEDS_RECEIVED,
        ReasonCode.PRICE_VARIANCE_OVER_TOL,
        ReasonCode.AMOUNT_VARIANCE_OVER_TOL,
    }
)


def run_exposure(run: RunRow) -> Decimal:
    """Largest amount at risk among the run's failing exposure checks."""
    amounts = [
        Decimal(str(c["amount_at_risk"]))
        for c in run.checks or []
        if c.get("status") == CheckStatus.fail.value
        and c.get("code") in EXPOSURE_CODES
        and c.get("amount_at_risk") is not None
    ]
    return max(amounts, default=Decimal("0.00"))


def effective_outcome(run: RunRow) -> str | None:
    return run.final_outcome or run.outcome


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: DB, days: Annotated[int, Query(ge=1, le=365)] = 30) -> StatsResponse:
    today = clock.today()
    first_day = today - timedelta(days=days - 1)
    runs = [
        r
        for r in db.scalars(select(RunRow).where(RunRow.outcome.is_not(None)))
        if r.created_at.astimezone(clock.IST).date() >= first_day
    ]
    processed = len(runs)
    value = sum((r.total or Decimal(0) for r in runs), Decimal("0.00"))
    touchless = sum(
        1
        for r in runs
        if r.decision_history
        and r.decision_history[0].get("outcome") == Outcome.APPROVE.value
        and not r.review_actions
    )
    live_ms = [
        ms for r in runs if r.source != RunSource.seed.value and (ms := duration_ms(r)) is not None
    ]
    exposure = sum(
        (run_exposure(r) for r in runs if r.final_outcome != Outcome.APPROVE.value), Decimal("0.00")
    )
    awaiting = (
        db.scalar(
            select(func.count())
            .select_from(RunRow)
            .where(RunRow.status == RunStatus.awaiting_review.value)
        )
        or 0
    )

    by_day: dict[str, dict[str, int]] = {}
    for i in range(days):
        by_day[(first_day + timedelta(days=i)).isoformat()] = {o.value: 0 for o in Outcome}
    reasons: dict[str, tuple[int, Decimal]] = {}
    routes: dict[str, int] = {}
    for r in runs:
        day = r.created_at.astimezone(clock.IST).date().isoformat()
        outcome = effective_outcome(r)
        if outcome and day in by_day:
            by_day[day][outcome] += 1
        first = (r.decision_history or [r.decision])[0] or {}
        if first.get("outcome") in (None, Outcome.APPROVE.value):
            continue
        code = first.get("primary_reason")
        if code:
            n, amount = reasons.get(code, (0, Decimal("0.00")))
            reasons[code] = (n + 1, amount + (r.total or Decimal(0)))
        route = first.get("route")
        if route and route != Route.none.value:
            routes[route] = routes.get(route, 0) + 1

    return StatsResponse(
        kpis=StatsKpis(
            processed=processed,
            value_processed=value,
            touchless_rate=round(touchless / processed, 4) if processed else 0.0,
            awaiting_review=awaiting,
            median_decision_ms=int(statistics.median(live_ms)) if live_ms else None,
            exposure_stopped=exposure,
        ),
        by_day=[StatsDay(date=d, **counts) for d, counts in by_day.items()],  # type: ignore[arg-type]
        by_reason=[
            StatsReason(code=ReasonCode(c), count=n, amount=a)
            for c, (n, a) in sorted(reasons.items(), key=lambda kv: (-kv[1][0], kv[0]))
        ],
        by_route=[
            StatsRoute(route=Route(k), count=v)
            for k, v in sorted(routes.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    )
