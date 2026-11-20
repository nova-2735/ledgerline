"""Decision policy: view, what-if preview, update."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ERROR_RESPONSES, not_implemented
from app.models.api import (
    PolicyPreviewRequest,
    PolicyPreviewResponse,
    PolicyResponse,
    PolicyUpdateRequest,
    PolicyVersionResponse,
)

router = APIRouter(tags=["policy"], responses=ERROR_RESPONSES)


@router.get("/policy", response_model=PolicyResponse)
def get_policy() -> PolicyResponse:
    not_implemented()


@router.post("/policy/preview", response_model=PolicyPreviewResponse)
def preview_policy(body: PolicyPreviewRequest) -> PolicyPreviewResponse:
    not_implemented()


@router.put("/policy", response_model=PolicyVersionResponse)
def update_policy(body: PolicyUpdateRequest) -> PolicyVersionResponse:
    not_implemented()
