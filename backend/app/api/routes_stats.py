"""Dashboard statistics."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ERROR_RESPONSES, not_implemented
from app.models.api import StatsResponse

router = APIRouter(tags=["stats"], responses=ERROR_RESPONSES)


@router.get("/stats", response_model=StatsResponse)
def get_stats(days: Annotated[int, Query(ge=1, le=365)] = 30) -> StatsResponse:
    not_implemented()
