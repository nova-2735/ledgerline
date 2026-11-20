"""Run events: an append-only, per-run ordered log that the live view tails (CONTRACTS §6)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.db import get_sessionmaker
from app.enums import StageName, StageStatus
from app.models.run import EventType, RunEvent
from app.orm import RunEventRow

MAX_ATTEMPTS = 5


def to_model(row: RunEventRow) -> RunEvent:
    return RunEvent(
        seq=row.seq,
        run_id=row.run_id,
        ts=row.ts,
        type=row.type,  # type: ignore[arg-type]
        stage=StageName(row.stage) if row.stage else None,
        status=StageStatus(row.status) if row.status else None,
        message=row.message,
        data=row.data,
    )


def emit(
    run_id: int,
    type: EventType,
    stage: StageName | None = None,
    status: StageStatus | None = None,
    message: str | None = None,
    data: dict[str, Any] | None = None,
) -> RunEvent:
    """Append one event with the next `seq` for the run, in its own short transaction.

    The runner and a review request can both write to a run, so a clash on (run_id, seq) is
    retried with the next number.
    """
    for attempt in range(MAX_ATTEMPTS):
        with get_sessionmaker()() as session:
            try:
                row = _insert(session, run_id, type, stage, status, message, data)
                session.commit()
            except IntegrityError:
                session.rollback()
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                continue
            return to_model(row)
    raise RuntimeError("unreachable")


def _insert(
    session: Session,
    run_id: int,
    type: EventType,
    stage: StageName | None,
    status: StageStatus | None,
    message: str | None,
    data: dict[str, Any] | None,
) -> RunEventRow:
    last = session.scalar(select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == run_id))
    row = RunEventRow(
        run_id=run_id,
        seq=(last or 0) + 1,
        ts=clock.now(),
        type=type,
        stage=stage.value if stage else None,
        status=status.value if status else None,
        message=message,
        data=data,
    )
    session.add(row)
    session.flush()
    return row


def events_after(session: Session, run_id: int, after: int = 0) -> list[RunEvent]:
    rows = session.scalars(
        select(RunEventRow)
        .where(RunEventRow.run_id == run_id, RunEventRow.seq > after)
        .order_by(RunEventRow.seq)
    )
    return [to_model(r) for r in rows]
