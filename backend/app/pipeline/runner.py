"""Run lifecycle: submit a document, execute the stages on a worker pool, resume after review.

Each execution owns one database session and commits after every stage, so the run view and
`GET /runs/{id}` are current while the run is in flight. Events are written in their own short
transactions (`events.emit`).

Two guards keep concurrent work consistent (one API process, `WORKERS` threads):
- `ledger_lock` serialises everything that reads or writes the invoice ledger: the rule stages
  (PO balances, duplicate history), the decision and the billing write. Two runs of the same
  invoice can't both see an empty history and both approve.
- the work gate lets a demo reset wait for in-flight runs and reviews and refuse new ones
  (`ResetInProgress`) while it drops and reseeds the tables.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.db import get_sessionmaker
from app.decide.policy import active_policy
from app.enums import Outcome, RunSource, RunStatus, StageName, StageStatus
from app.ingest.storage import store_document
from app.llm.base import (
    BudgetExceededError,
    FakeProviderError,
    LLMClient,
    LLMConfigError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    get_client,
)
from app.models.checks import CheckResult, MatchingView
from app.models.decision import Decision
from app.models.extraction import InvoiceExtraction
from app.orm import InvoiceLedgerRow, ReviewActionRow, RunRow
from app.reference.ledger import BilledLine, Ledger, LedgerEntry
from app.reference.purchase_orders import get_po
from app.rules.base import ReviewOverrides, decimal_value, money_currency, q2, text_value
from app.rules.registry import STAGES as RULE_STAGES

from .events import emit
from .stages import (
    STAGE_FUNCS,
    STAGE_ORDER,
    RunState,
    apply_corrections,
    ensure_doc_read,
    pending,
    run_stage,
    stage_index,
)

log = logging.getLogger(__name__)

STAGE_LABEL = {
    StageName.intake: "receiving the file",
    StageName.read_document: "reading the document",
    StageName.extract_fields: "reading the invoice fields",
    StageName.validate_document: "checking the document",
    StageName.identify_vendor: "identifying the vendor",
    StageName.check_tax: "checking GST",
    StageName.resolve_po: "finding the purchase order",
    StageName.match_lines: "matching lines",
    StageName.check_duplicates: "checking for duplicates",
    StageName.decide: "deciding",
    StageName.explain_route: "preparing the explanation",
}


@dataclass(frozen=True)
class SubmitMeta:
    source: RunSource = RunSource.upload
    scenario_id: str | None = None
    sender_name: str | None = None
    sender_email: str | None = None
    subject: str | None = None


# --- worker pool and work gate -------------------------------------------------------------------


class ResetInProgress(RuntimeError):
    """New work is refused while the demo world is being reset."""


class ResetTimeout(RuntimeError):
    """A reset gave up waiting for in-flight work to finish."""


_lock = threading.Lock()
_pool: ThreadPoolExecutor | None = None

# The work gate: `_active` counts submissions, reviews and scheduled jobs (queued or running).
_gate = threading.Condition()
_active = 0
_reset_owner: int | None = None  # thread running a reset, if any
_local = threading.local()

# Rule stages → decide → billing write, one run at a time (see the module docstring).
ledger_lock = threading.RLock()


def _acquire() -> None:
    global _active
    with _gate:
        nested = getattr(_local, "depth", 0) > 0
        if _reset_owner is not None and _reset_owner != threading.get_ident() and not nested:
            raise ResetInProgress("The demo is being reset. Try again in a moment.")
        _active += 1


def _release() -> None:
    global _active
    with _gate:
        _active -= 1
        _gate.notify_all()


@contextmanager
def work() -> Iterator[None]:
    """Hold a work slot for a submission or review. Raises `ResetInProgress` while a reset runs
    (except on the reset's own thread, or nested inside another slot)."""
    _acquire()
    _local.depth = getattr(_local, "depth", 0) + 1
    try:
        yield
    finally:
        _local.depth -= 1
        _release()


@contextmanager
def exclusive(timeout: float) -> Iterator[None]:
    """Run a reset: refuse new work, wait up to `timeout` s for in-flight work, then yield.
    Raises `ResetInProgress` when another reset is running and `ResetTimeout` when work doesn't
    finish in time; new work is accepted again in both cases."""
    global _reset_owner
    with _gate:
        if _reset_owner is not None:
            raise ResetInProgress("A reset is already running.")
        _reset_owner = threading.get_ident()
        if not _gate.wait_for(lambda: _active == 0, timeout):
            _reset_owner = None
            _gate.notify_all()
            raise ResetTimeout(
                "Some invoices are still being processed, so the demo wasn't reset. "
                "Try again in a minute."
            )
    try:
        yield
    finally:
        with _gate:
            _reset_owner = None
            _gate.notify_all()


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=get_settings().workers, thread_name_prefix="pipeline"
            )
        return _pool


def schedule(fn: Callable[..., None], *args: Any, **kwargs: Any) -> None:
    """Run `fn` on the worker pool; it holds a work slot from now until it finishes."""
    _acquire()
    try:
        future = _executor().submit(fn, *args, **kwargs)
    except BaseException:
        _release()
        raise
    future.add_done_callback(_done)


def _done(_: Future[None]) -> None:
    _release()


def wait_idle(timeout: float = 120) -> bool:
    """Wait until no submission, review or scheduled run is in flight. True when idle."""
    with _gate:
        return _gate.wait_for(lambda: _active == 0, timeout)


def shutdown() -> None:
    global _pool
    wait_idle()
    with _lock:
        if _pool is not None:
            _pool.shutdown(wait=True)
        _pool = None


# --- submit / execute / resume -------------------------------------------------------------------


def submit(
    data: bytes,
    filename: str,
    meta: SubmitMeta | None = None,
    *,
    force_fresh: bool = False,
    background: bool = True,
    client: LLMClient | None = None,
    polish: bool | None = None,
) -> int:
    """Store the document, create a queued run and start it. Raises `IntakeError` when the file
    can't be accepted (too large, not a PDF, encrypted, too many pages)."""
    with work():
        return _submit(
            data, filename, meta or SubmitMeta(), force_fresh, background, client, polish
        )


def _submit(
    data: bytes,
    filename: str,
    meta: SubmitMeta,
    force_fresh: bool,
    background: bool,
    client: LLMClient | None,
    polish: bool | None,
) -> int:
    stored = store_document(data, filename)
    with get_sessionmaker()() as session:
        run = RunRow(
            display_id=f"pending-{stored.sha256[:12]}-{clock.now().timestamp()}",
            document_id=stored.id,
            source=meta.source.value,
            scenario_id=meta.scenario_id,
            sender_name=meta.sender_name,
            sender_email=meta.sender_email,
            subject=meta.subject,
            status=RunStatus.queued.value,
            created_at=clock.now(),
            stages=[pending(n).model_dump(mode="json") for n in STAGE_ORDER],
            decision_history=[],
            overrides=ReviewOverrides().model_dump(mode="json"),
        )
        session.add(run)
        session.flush()
        run.display_id = f"R-{run.id:04d}"
        session.commit()
        run_id = run.id
    emit(run_id, "run.created", message="Invoice received.", data={"filename": filename})
    if background:
        schedule(execute, run_id, force_fresh=force_fresh, client=client, polish=polish)
    else:
        execute(run_id, force_fresh=force_fresh, client=client, polish=polish)
    return run_id


def _state(
    session: Session,
    run: RunRow,
    *,
    client: LLMClient | None,
    polish: bool | None,
    force_fresh: bool = False,
) -> RunState:
    doc = run.document
    return RunState(
        run_id=run.id,
        session=session,
        filename=doc.filename,
        sha256=doc.sha256,
        data=doc.bytes,
        page_count=doc.page_count,
        client=client or get_client(get_settings()),
        policy=active_policy(),
        sender_email=run.sender_email,
        force_fresh=force_fresh,
        polish=polish,
        overrides=ReviewOverrides.model_validate(run.overrides or {}),
        decision_version=len(run.decision_history or []) + 1,
        persist=_persist,
    )


def execute(
    run_id: int,
    *,
    force_fresh: bool = False,
    client: LLMClient | None = None,
    polish: bool | None = None,
) -> None:
    """Run every stage of a queued run."""
    with get_sessionmaker()() as session:
        run = _get(session, run_id)
        try:
            state = _state(session, run, client=client, polish=polish, force_fresh=force_fresh)
        except Exception as exc:  # e.g. a missing provider key
            _fail_before_start(session, run, exc)
            return
        state.stages = {n: pending(n) for n in STAGE_ORDER}
        run.status = RunStatus.running.value
        run.started_at = clock.now()
        session.commit()
        emit(run_id, "run.started", message="Processing started.")
        _run_from(state, StageName.intake)


def resume(
    run_id: int,
    from_stage: StageName,
    *,
    message: str | None = None,
    data: dict[str, Any] | None = None,
    client: LLMClient | None = None,
    polish: bool | None = None,
) -> None:
    """Re-run `from_stage` onwards with the run's current review overrides. Earlier rule stages
    are re-evaluated silently, so checks that review resolved show as resolved."""
    with get_sessionmaker()() as session:
        run = _get(session, run_id)
        try:
            state = _state(session, run, client=client, polish=polish)
        except Exception as exc:
            _fail_before_start(session, run, exc)
            return
        state.stages = {s.name: s for s in _stages(run)}
        if run.extraction is not None:
            state.extraction = InvoiceExtraction.model_validate(run.extraction)
        if run.matching is not None:
            state.matching = MatchingView.model_validate(run.matching)
        state.cached_extraction = run.cached_extraction
        if state.extraction is not None and state.overrides.field_corrections:
            state.extraction = apply_corrections(
                state.extraction, state.overrides, ensure_doc_read(state)
            )
        for name in STAGE_ORDER:
            if stage_index(name) >= stage_index(from_stage):
                state.stages[name] = pending(name)
        # A reopened run stops counting as billed while it is re-checked.
        with ledger_lock:
            if session.get(InvoiceLedgerRow, run_id) is not None:
                Ledger(session).set_outcome(run_id, None)
            run.final_outcome = None
            run.status = RunStatus.running.value
            run.stages = _dump_stages(state)
            session.commit()
        emit(
            run_id,
            "run.resumed",
            message=message or "Resumed after review",
            data={"from_stage": from_stage.value, **(data or {})},
        )
        _run_from(state, from_stage)


def _get(session: Session, run_id: int) -> RunRow:
    run = session.get(RunRow, run_id)
    if run is None:
        raise LookupError(f"run {run_id} not found")
    return run


def _run_from(state: RunState, start: StageName) -> None:
    current = start
    # From the first rule stage until the outcome is committed, hold the ledger lock: the rules
    # read PO balances and duplicate history, and the outcome writes billing.
    currency = state.extraction.currency if state.extraction is not None else "INR"
    with ExitStack() as held, money_currency(currency):
        try:
            for name in STAGE_ORDER:
                current = name
                if name == RULE_STAGES[0]:
                    held.enter_context(ledger_lock)
                if stage_index(name) < stage_index(start):
                    if name in RULE_STAGES and state.extraction is not None:
                        run_stage(state, name, STAGE_FUNCS[name], silent=True)
                    continue
                run_stage(state, name, STAGE_FUNCS[name])
                if name == StageName.decide and state.decision is not None:
                    d = state.decision
                    emit(
                        state.run_id,
                        "decision.made",
                        message=d.headline,
                        data={
                            "decision": d.model_dump(mode="json"),
                            "outcome": d.outcome.value,
                            "route": d.route.value,
                        },
                    )
            _finalize(state)
        except Exception as exc:
            log.exception("run %s failed in %s", state.run_id, current.value)
            state.session.rollback()
            _fail(state, current, exc)


# --- persistence ---------------------------------------------------------------------------------


def _stages(run: RunRow) -> list[Any]:
    from app.models.run import StageState

    by_name = {s["name"]: StageState.model_validate(s) for s in run.stages or []}
    return [by_name.get(n.value) or pending(n) for n in STAGE_ORDER]


def _dump_stages(state: RunState) -> list[dict[str, Any]]:
    return [(state.stages.get(n) or pending(n)).model_dump(mode="json") for n in STAGE_ORDER]


def _dump_checks(checks: list[CheckResult]) -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in checks]


def _persist(state: RunState) -> None:
    run = _get(state.session, state.run_id)
    run.stages = _dump_stages(state)
    if state.results:
        run.checks = _dump_checks(state.checks)
    ex = state.extraction
    if ex is not None:
        run.extraction = ex.model_dump(mode="json")
        run.cached_extraction = state.cached_extraction
        run.invoice_number = text_value(ex.invoice_number)
        run.invoice_number_canonical = ex.invoice_number_canonical
        inv_date = ex.invoice_date.value
        run.invoice_date = inv_date if isinstance(inv_date, date) else None
        run.total = decimal_value(ex.total)
    ctx = state.ctx
    if ctx is not None:
        run.vendor_id = ctx.vendor.vendor_id if ctx.vendor else None
        run.po_number = ctx.po.po_number if ctx.po else None
    if state.matching is not None:
        run.matching = state.matching.model_dump(mode="json")
    state.session.commit()


def billing_from_view(session: Session, view: MatchingView | None) -> list[BilledLine]:
    """PO lines an approved invoice bills (RULES §7): invoiced qty for 1:1 rows; a bundled row
    bills each PO line's ordered quantity, with the amount split by the PO's expected values."""
    if view is None or view.po_number is None:
        return []
    po = get_po(session, view.po_number)
    if po is None:
        return []
    by_no = {pl.line_no: pl for pl in po.lines}
    out: list[BilledLine] = []
    for row in view.rows:
        if row.amount_invoice is None:
            continue
        if row.kind == "one_to_one" and row.qty_invoiced is not None:
            out.append(
                BilledLine(
                    po_line_no=row.po_line_nos[0], qty=row.qty_invoiced, amount=row.amount_invoice
                )
            )
        elif row.kind == "bundled":
            weights = [q2(by_no[n].quantity * by_no[n].unit_price) for n in row.po_line_nos]
            total = sum(weights, Decimal())
            parts = [
                q2(row.amount_invoice * w / total) if total else Decimal(0) for w in weights[:-1]
            ]
            parts.append(q2(row.amount_invoice - sum(parts, Decimal())))
            for n, part in zip(row.po_line_nos, parts, strict=True):
                out.append(BilledLine(po_line_no=n, qty=by_no[n].quantity, amount=part))
    return out


def record_outcome(session: Session, run: RunRow, decision: Decision) -> None:
    """Write the decision onto the run and the invoice ledger (billing on final APPROVE), and
    link the latest review action to the decision version it produced."""
    run.decision = decision.model_dump(mode="json")
    run.decision_history = [*(run.decision_history or []), run.decision]
    run.outcome = decision.outcome.value
    run.route = decision.route.value
    run.primary_reason = decision.primary_reason.value if decision.primary_reason else None
    run.policy_version = decision.policy_version
    final = decision.outcome if decision.final else None
    run.final_outcome = final.value if final else None
    run.status = (RunStatus.completed if decision.final else RunStatus.awaiting_review).value
    run.finished_at = clock.now()
    matching = MatchingView.model_validate(run.matching) if run.matching else None
    billed = billing_from_view(session, matching) if final == Outcome.APPROVE else []
    Ledger(session).upsert_entry(
        LedgerEntry(
            run_id=run.id,
            vendor_id=run.vendor_id,
            invoice_number=run.invoice_number,
            invoice_number_canonical=run.invoice_number_canonical,
            invoice_date=run.invoice_date,
            total=run.total,
            po_number=run.po_number,
            file_sha256=run.document.sha256,
            final_outcome=final,
            billed_lines=billed,
        )
    )
    action = session.scalar(
        select(ReviewActionRow)
        .where(
            ReviewActionRow.run_id == run.id, ReviewActionRow.resulting_decision_version.is_(None)
        )
        .order_by(ReviewActionRow.id.desc())
    )
    if action is not None:
        action.resulting_decision_version = decision.version


def terminal_event(run: RunRow, decision: Decision) -> None:
    data = {
        "outcome": decision.outcome.value,
        "route": decision.route.value,
        "final_outcome": run.final_outcome,
        "version": decision.version,
    }
    if decision.final:
        emit(run.id, "run.completed", message=decision.headline, data=data)
    else:
        emit(run.id, "run.awaiting_review", message=decision.headline, data=data)


def _finalize(state: RunState) -> None:
    if state.decision is None:
        raise RuntimeError("the run finished without a decision")
    _persist(state)
    run = _get(state.session, state.run_id)
    record_outcome(state.session, run, state.decision)
    state.session.commit()
    terminal_event(run, state.decision)


# --- failures ------------------------------------------------------------------------------------


def friendly_error(stage: StageName, exc: Exception) -> str:
    if isinstance(exc, BudgetExceededError):
        return (
            "The hourly limit for live model calls has been reached. Try again later; "
            "saved readings are still available."
        )
    if isinstance(exc, LLMRateLimitError):
        return "The model provider is busy (rate limited). Please try again in a minute."
    if isinstance(exc, LLMTimeoutError):
        return "The model took too long to read the invoice. Please try again."
    if isinstance(exc, LLMUnavailableError):
        return "The model provider is unavailable right now. Please try again shortly."
    if isinstance(exc, LLMConfigError):
        return f"The model provider isn't configured: {exc}"
    if isinstance(exc, FakeProviderError):
        return (
            "The offline reader only knows the generated demo invoices. Switch to the live "
            "model to read other files."
        )
    return f"Something went wrong while {STAGE_LABEL[stage]}: {exc}"


def _fail(state: RunState, stage: StageName, exc: Exception) -> None:
    message = friendly_error(stage, exc)
    started = state.stages.get(stage)
    now = clock.now()
    state.stages[stage] = (started or pending(stage)).model_copy(
        update={
            "status": StageStatus.error,
            "finished_at": now,
            "summary": message,
            "started_at": (started.started_at if started else None) or now,
        }
    )
    run = _get(state.session, state.run_id)
    run.stages = _dump_stages(state)
    run.status = RunStatus.failed.value
    run.finished_at = now
    state.session.commit()
    emit(
        state.run_id,
        "stage.completed",
        stage,
        StageStatus.error,
        message,
        {"duration_ms": None, "check_rule_ids": [], "checks": [], "detail": {}},
    )
    emit(
        state.run_id,
        "run.failed",
        message=message,
        data={"stage": stage.value, "error": type(exc).__name__},
    )


def _fail_before_start(session: Session, run: RunRow, exc: Exception) -> None:
    message = friendly_error(StageName.intake, exc)
    run.status = RunStatus.failed.value
    run.finished_at = clock.now()
    session.commit()
    emit(run.id, "run.failed", message=message, data={"stage": None, "error": type(exc).__name__})
