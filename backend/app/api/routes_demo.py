"""Demo world: inbox, demo runs and reset."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Path

from app.api.deps import ERROR_RESPONSES, not_implemented
from app.models.api import DemoInboxItem, DemoRunRequest, ResetResponse, RunCreated

router = APIRouter(tags=["demo"], responses=ERROR_RESPONSES)


@router.post("/demo/runs/{doc_id}", status_code=202, response_model=RunCreated)
def create_demo_run(
    doc_id: Annotated[str, Path(pattern=r"^S\d{2}$")],
    body: Annotated[DemoRunRequest | None, Body()] = None,
) -> RunCreated:
    not_implemented()


@router.get("/demo/inbox", response_model=list[DemoInboxItem])
def get_demo_inbox() -> list[DemoInboxItem]:
    not_implemented()


@router.post("/demo/reset", response_model=ResetResponse)
def reset_demo() -> ResetResponse:
    not_implemented()
