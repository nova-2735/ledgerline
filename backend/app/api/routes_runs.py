"""Runs: upload, list, detail, live events, document, page images, audit export."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func, or_, select

from app.api.deps import DB, ERROR_RESPONSES, APIError, not_found
from app.api.views import run_detail, run_summary, vendor_names
from app.config import get_settings
from app.db import get_sessionmaker
from app.enums import Outcome, Route, RunSource, RunStatus
from app.export.audit_pdf import audit_pdf
from app.ingest.reader import IntakeError
from app.ingest.render import render_page_png
from app.ingest.storage import ensure_file
from app.models.api import AuditExport, RunCreated, RunList
from app.models.run import RunDetail
from app.orm import DocumentRow, RunRow, VendorRow
from app.pipeline import runner
from app.pipeline.events import events_after

router = APIRouter(tags=["runs"], responses=ERROR_RESPONSES)

TERMINAL = frozenset({"run.completed", "run.awaiting_review", "run.failed"})
POLL_S = 0.25
HEARTBEAT_S = 15.0
MAX_STREAM_S = 15 * 60


def intake_error(exc: IntakeError) -> APIError:
    status = 413 if exc.code == "too_large" else 422
    return APIError(status, exc.code, exc.message)


@router.post("/runs", status_code=202, response_model=RunCreated)
async def create_run(
    file: Annotated[UploadFile, File()],
    force_fresh: Annotated[bool, Form()] = False,
) -> RunCreated:
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    try:
        run_id = await asyncio.to_thread(
            runner.submit,
            data,
            file.filename or "invoice.pdf",
            runner.SubmitMeta(source=RunSource.upload),
            force_fresh=force_fresh,
        )
    except IntakeError as exc:
        raise intake_error(exc) from exc
    return RunCreated(run_id=run_id)


@router.get("/runs", response_model=RunList)
def list_runs(
    db: DB,
    outcome: Outcome | None = None,
    status: RunStatus | None = None,
    route: Route | None = None,
    vendor_id: str | None = None,
    source: RunSource | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunList:
    stmt = select(RunRow).join(DocumentRow, RunRow.document_id == DocumentRow.id)
    if outcome is not None:
        stmt = stmt.where(func.coalesce(RunRow.final_outcome, RunRow.outcome) == outcome.value)
    if status is not None:
        stmt = stmt.where(RunRow.status == status.value)
    if route is not None:
        stmt = stmt.where(RunRow.route == route.value)
    if vendor_id:
        stmt = stmt.where(RunRow.vendor_id == vendor_id)
    if source is not None:
        stmt = stmt.where(RunRow.source == source.value)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.outerjoin(VendorRow, RunRow.vendor_id == VendorRow.vendor_id).where(
            or_(
                RunRow.display_id.ilike(like),
                RunRow.invoice_number.ilike(like),
                RunRow.po_number.ilike(like),
                RunRow.scenario_id.ilike(like),
                RunRow.subject.ilike(like),
                DocumentRow.filename.ilike(like),
                VendorRow.legal_name.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(RunRow.created_at.desc(), RunRow.id.desc()).limit(limit).offset(offset)
    )
    names = vendor_names(db)
    return RunList(items=[run_summary(r, names) for r in rows], total=total)


def get_run_row(db: DB, run_id: int) -> RunRow:
    run = db.get(RunRow, run_id)
    if run is None:
        raise not_found(f"Run {run_id}")
    return run


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int, db: DB) -> RunDetail:
    return run_detail(db, get_run_row(db, run_id))


def _sse(event_id: int, type_: str, data: str) -> str:
    return f"id: {event_id}\nevent: {type_}\ndata: {data}\n\n"


def _settled(run_id: int, seq: int) -> bool:
    """No event after `seq` and the run isn't executing (a review may have just requeued it)."""
    with get_sessionmaker()() as session:
        if events_after(session, run_id, seq):
            return False
        run = session.get(RunRow, run_id)
        return run is None or run.status not in (RunStatus.queued.value, RunStatus.running.value)


async def _stream(run_id: int, after: int) -> AsyncIterator[str]:
    cursor = after
    started = last_sent = time.monotonic()
    yield "retry: 1000\n\n"
    while time.monotonic() - started < MAX_STREAM_S:
        with get_sessionmaker()() as session:
            batch = events_after(session, run_id, cursor)
        for ev in batch:
            cursor = ev.seq
            yield _sse(ev.seq, ev.type, json.dumps(ev.model_dump(mode="json")))
            last_sent = time.monotonic()
        # A replay from the start passes earlier terminal events (before a review and resume);
        # close only after the latest one, once the run is no longer queued or running.
        if batch and batch[-1].type in TERMINAL and _settled(run_id, cursor):
            return
        if time.monotonic() - last_sent >= HEARTBEAT_S:
            yield ": keep-alive\n\n"
            last_sent = time.monotonic()
        await asyncio.sleep(POLL_S)


@router.get(
    "/runs/{run_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-sent events; each `data:` line is a RunEvent JSON object.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def stream_run_events(
    run_id: int,
    db: DB,
    after: Annotated[int | None, Query(ge=0)] = None,
    code: str | None = None,
) -> StreamingResponse:
    get_run_row(db, run_id)
    return StreamingResponse(
        _stream(run_id, after or 0),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/runs/{run_id}/document",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The original PDF"}},
)
def get_run_document(run_id: int, db: DB, code: str | None = None) -> Response:
    doc = get_run_row(db, run_id).document
    safe = doc.filename.replace('"', "")
    return Response(
        content=doc.bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe}"'},
    )


@router.get(
    "/runs/{run_id}/pages/{n}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "Rendered page image"}},
)
def get_run_page(
    run_id: int,
    n: int,
    db: DB,
    scale: Annotated[float, Query(gt=0, le=4)] = 1.5,
    code: str | None = None,
) -> FileResponse:
    doc = get_run_row(db, run_id).document
    if not 1 <= n <= doc.page_count:
        raise not_found(f"Page {n}")
    ensure_file(doc.sha256, doc.bytes)
    path = render_page_png(doc.sha256, n - 1, max(scale, 0.25))
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@router.get(
    "/runs/{run_id}/audit.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "Audit record (PDF)"}},
)
def get_run_audit_pdf(run_id: int, db: DB, code: str | None = None) -> Response:
    """One-page summary (decision, key numbers, next step), then checks, extracted fields, stage
    timeline, review actions and decision history."""
    run = get_run_row(db, run_id)
    detail = run_detail(db, run)
    pdf = audit_pdf(detail, events_after(db, run_id, 0))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{detail.display_id}-audit.pdf"'},
    )


@router.get("/runs/{run_id}/audit", response_model=AuditExport)
def get_run_audit(run_id: int, db: DB) -> AuditExport:
    run = get_run_row(db, run_id)
    detail = run_detail(db, run)
    raw = detail.extraction.meta.raw.model_dump(mode="json") if detail.extraction else None
    return AuditExport(run=detail, events=events_after(db, run_id, 0), raw_model_output=raw)
