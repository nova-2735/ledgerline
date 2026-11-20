"""Demo world: inbox, demo runs and reset."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Path
from sqlalchemy import select

from app.api.deps import DB, ERROR_RESPONSES, APIError, not_found
from app.api.routes_runs import intake_error
from app.demo.seed import load_manifest, seed, world_dir
from app.enums import RunSource
from app.ingest.reader import IntakeError
from app.models.api import DemoInboxItem, DemoRunRequest, ResetResponse, RunCreated
from app.orm import RunRow
from app.pipeline import runner

router = APIRouter(tags=["demo"], responses=ERROR_RESPONSES)


def _manifest() -> dict[str, Any]:
    world = world_dir()
    if not (world / "manifest.json").is_file():
        raise APIError(404, "demo_not_generated", "The demo world hasn't been generated yet.")
    return load_manifest(world)


def _inbox(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in manifest["documents"].items() if v["kind"] == "inbox"}


@router.post("/demo/runs/{doc_id}", status_code=202, response_model=RunCreated)
def create_demo_run(
    doc_id: Annotated[str, Path(pattern=r"^S\d{2}$")],
    body: Annotated[DemoRunRequest | None, Body()] = None,
) -> RunCreated:
    info = _inbox(_manifest()).get(doc_id)
    if info is None:
        raise not_found(f"Demo document {doc_id}")
    email = info.get("email") or {}
    data = (world_dir() / info["file"]).read_bytes()
    try:
        run_id = runner.submit(
            data,
            f"{doc_id}.pdf",
            runner.SubmitMeta(
                source=RunSource.demo,
                scenario_id=doc_id,
                sender_name=email.get("sender_name"),
                sender_email=email.get("sender_email"),
                subject=email.get("subject"),
            ),
            force_fresh=bool(body and body.force_fresh),
        )
    except IntakeError as exc:
        raise intake_error(exc) from exc
    return RunCreated(run_id=run_id)


@router.get("/demo/inbox", response_model=list[DemoInboxItem])
def get_demo_inbox(db: DB) -> list[DemoInboxItem]:
    inbox = _inbox(_manifest())
    processed: dict[str, list[int]] = {}
    for run_id, scenario in db.execute(
        select(RunRow.id, RunRow.scenario_id)
        .where(RunRow.source == RunSource.demo.value)
        .order_by(RunRow.id)
    ):
        if scenario:
            processed.setdefault(scenario, []).append(run_id)
    items = []
    for doc_id, info in sorted(inbox.items()):
        email = info.get("email") or {}
        items.append(
            DemoInboxItem(
                doc_id=doc_id,
                sender_name=email.get("sender_name") or "",
                sender_email=email.get("sender_email") or "",
                subject=email.get("subject") or "",
                received_at=datetime.fromisoformat(email["received_at"]),
                filename=f"{doc_id}.pdf",
                title=info.get("title") or doc_id,
                tags=list(info.get("tags") or []),
                is_edge_case=bool(info.get("edge_case")),
                processed_run_ids=processed.get(doc_id, []),
            )
        )
    items.sort(key=lambda i: i.received_at, reverse=True)
    return items


@router.post("/demo/reset", response_model=ResetResponse)
def reset_demo() -> ResetResponse:
    return ResetResponse(status="ok", runs=seed())
