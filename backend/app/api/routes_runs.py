"""Runs: upload, list, detail, live events, document, page images, audit export."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import Response

from app.api.deps import ERROR_RESPONSES, not_implemented
from app.enums import Outcome, Route, RunSource, RunStatus
from app.models.api import AuditExport, RunCreated, RunList
from app.models.run import RunDetail

router = APIRouter(tags=["runs"], responses=ERROR_RESPONSES)

NOT_IMPLEMENTED_SSE = (
    'event: error\ndata: {"detail": "not implemented", "code": "not_implemented"}\n\n'
)


@router.post("/runs", status_code=202, response_model=RunCreated)
def create_run(
    file: Annotated[UploadFile, File()],
    force_fresh: Annotated[bool, Form()] = False,
) -> RunCreated:
    not_implemented()


@router.get("/runs", response_model=RunList)
def list_runs(
    outcome: Outcome | None = None,
    status: RunStatus | None = None,
    route: Route | None = None,
    vendor_id: str | None = None,
    source: RunSource | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunList:
    not_implemented()


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int) -> RunDetail:
    not_implemented()


@router.get(
    "/runs/{run_id}/events",
    response_class=Response,
    responses={
        200: {
            "description": "Server-sent events; each `data:` line is a RunEvent JSON object.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def stream_run_events(
    run_id: int,
    after: Annotated[int | None, Query(ge=0)] = None,
    code: str | None = None,
) -> Response:
    return Response(content=NOT_IMPLEMENTED_SSE, status_code=501, media_type="text/event-stream")


@router.get(
    "/runs/{run_id}/document",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The original PDF"}},
)
def get_run_document(run_id: int, code: str | None = None) -> Response:
    not_implemented()


@router.get(
    "/runs/{run_id}/pages/{n}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "Rendered page image"}},
)
def get_run_page(
    run_id: int,
    n: int,
    scale: Annotated[float, Query(gt=0, le=4)] = 1.5,
    code: str | None = None,
) -> Response:
    not_implemented()


@router.get("/runs/{run_id}/audit", response_model=AuditExport)
def get_run_audit(run_id: int) -> AuditExport:
    not_implemented()
