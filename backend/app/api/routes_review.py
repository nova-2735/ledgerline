"""Review actions and the review queue."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ERROR_RESPONSES, not_implemented
from app.enums import Route
from app.models.api import QueueResponse, ReviewRequest
from app.models.run import RunDetail

router = APIRouter(tags=["review"], responses=ERROR_RESPONSES)


@router.post("/runs/{run_id}/review", response_model=RunDetail)
def review_run(run_id: int, body: ReviewRequest) -> RunDetail:
    not_implemented()


@router.get("/queue", response_model=QueueResponse)
def get_queue(route: Route | None = None) -> QueueResponse:
    not_implemented()
