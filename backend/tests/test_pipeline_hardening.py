"""Regression tests for the pipeline review fixes: concurrency, posting guarantees, review
guards, reset safety, model-call audit events, SSE replay, event retries and policy preview."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import clock
from app.api.routes_policy import _decide
from app.config import get_settings
from app.db import get_sessionmaker
from app.decide.policy import active_policy
from app.demo import seed as seed_mod
from app.demo.seed import load_manifest, world_dir
from app.enums import Outcome, StageName
from app.llm.base import CallMeta, LineGroup
from app.llm.fake import FakeClient
from app.models.extraction import InvoiceExtraction
from app.models.reference import PurchaseOrder
from app.orm import InvoiceLedgerRow, RunEventRow, RunRow
from app.pipeline import events, runner, stages
from app.rules.base import ReviewOverrides, build_context
from tests.helpers.seeded import replay, wait_run

PRIYA = "Priya Nair (AP)"


def _demo(api: TestClient, doc_id: str) -> dict[str, Any]:
    run_id = api.post(f"/api/demo/runs/{doc_id}").json()["run_id"]
    return wait_run(api, run_id)


def _review(api: TestClient, run_id: int, **body: Any) -> Any:
    return api.post(f"/api/runs/{run_id}/review", json={"reviewer": PRIYA, **body})


def _pdf(doc_id: str) -> bytes:
    world = world_dir()
    return (world / load_manifest(world)["documents"][doc_id]["file"]).read_bytes()


# --- B08: concurrent runs ------------------------------------------------------------------------


def test_concurrent_copies_of_one_invoice_approve_once(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: two simultaneous S01 submissions both reached final APPROVE, because each
    read the duplicate history and PO balances before the other committed its billing."""
    assert get_settings().workers >= 2
    both_read = threading.Barrier(2, timeout=10)
    extract = stages.STAGE_FUNCS[StageName.extract_fields]

    def in_step(state: stages.RunState) -> stages.StageResult:
        result = extract(state)
        both_read.wait()  # both runs leave extraction together and race for the rules
        return result

    monkeypatch.setitem(stages.STAGE_FUNCS, StageName.extract_fields, in_step)
    ids = [api.post("/api/demo/runs/S01").json()["run_id"] for _ in range(2)]
    runs = [wait_run(api, i) for i in ids]
    assert sorted(r["final_outcome"] for r in runs) == ["APPROVE", "REJECT"]
    rejected = next(r for r in runs if r["final_outcome"] == "REJECT")
    assert rejected["primary_reason"] == "DUPLICATE_SAME_FILE"
    with get_sessionmaker()() as s:
        billed = s.scalars(
            select(InvoiceLedgerRow).where(
                InvoiceLedgerRow.run_id.in_(ids), InvoiceLedgerRow.final_outcome == "APPROVE"
            )
        ).all()
    assert len(billed) == 1 and billed[0].billed_lines


# --- B06–B08: no final APPROVE without a posting ------------------------------------------------


def test_reviewer_cant_approve_with_the_invoice_number_missing(api: TestClient) -> None:
    """Regression: a reviewer could approve S10 with no invoice number (posting=null)."""
    run = _demo(api, "S10")
    resp = _review(api, run["id"], action="approve", note="Looks fine")
    assert (resp.status_code, resp.json()["code"]) == (409, "field_missing")
    after = api.get(f"/api/runs/{run['id']}").json()
    assert after["status"] == "awaiting_review" and after["review_actions"] == []


def test_reviewer_cant_approve_without_a_posting(api: TestClient) -> None:
    run = _demo(api, "S11")  # unknown vendor: nothing to post to
    resp = _review(api, run["id"], action="approve", note="Onboarding later")
    assert (resp.status_code, resp.json()["code"]) == (409, "posting_incomplete")
    assert "vendor master" in resp.json()["detail"]


# --- B06/B08: field corrections keep the finding -------------------------------------------------


def test_field_correction_keeps_the_original_finding_resolved(api: TestClient) -> None:
    """Regression: correcting S10's invoice number replaced the D02 failure with a pass, losing
    the reviewer's resolution; corrected fields also lacked the human_verified validator."""
    run = _demo(api, "S10")
    note = "Vendor confirmed the number by phone"
    resp = _review(api, run["id"], action="correct_fields",
                   field_corrections={"invoice_number": "DCC/1131/26"}, note=note)  # fmt: skip
    assert resp.status_code == 200
    after = wait_run(api, run["id"])
    assert after["outcome"] == "APPROVE"
    [d02] = [c for c in after["checks"] if c["code"] == "FIELD_MISSING_INVOICE_NUMBER"]
    assert d02["status"] == "fail" and d02["resolved_by_review"]
    assert f"Resolved by {PRIYA}: {note}" in d02["message"]
    others = [c for c in after["checks"] if c["rule_id"] == "D02_required"]
    assert [c["evidence"].get("field") for c in others] == [
        "invoice_number", "invoice_date", "total", "supplier",
    ]  # fmt: skip
    assert "human_verified" in after["extraction"]["invoice_number"]["validators"]
    stage = next(s for s in after["stages"] if s["name"] == "validate_document")
    assert stage["status"] == "warned" and "resolved by review" in stage["summary"]


# --- B08: reset safety ---------------------------------------------------------------------------


@contextmanager
def _busy() -> Iterator[None]:
    """Hold a work slot on another thread, like a run in flight."""
    holding, release = threading.Event(), threading.Event()

    def hold() -> None:
        with runner.work():
            holding.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    holding.wait(5)
    try:
        yield
    finally:
        release.set()
        t.join(5)


@contextmanager
def _resetting() -> Iterator[None]:
    """Hold the reset gate on another thread, like a reset in progress."""
    inside, done = threading.Event(), threading.Event()

    def hold() -> None:
        with runner.exclusive(5):
            inside.set()
            done.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    inside.wait(5)
    try:
        yield
    finally:
        done.set()
        t.join(5)


def test_uploads_and_reviews_get_409_during_reset(api: TestClient) -> None:
    """Regression: an upload or review could start while reset dropped and reseeded tables."""
    run = _demo(api, "S04")
    with _resetting():
        demo = api.post("/api/demo/runs/S01")
        assert (demo.status_code, demo.json()["code"]) == (409, "reset_in_progress")
        upload = api.post("/api/runs", files={"file": ("S01.pdf", _pdf("S01"), "application/pdf")})
        assert upload.status_code == 409
        review = _review(api, run["id"], action="reject", note="x")
        assert (review.status_code, review.json()["code"]) == (409, "reset_in_progress")
        again = api.post("/api/demo/reset")
        assert (again.status_code, again.json()["code"]) == (409, "reset_in_progress")
    assert api.post("/api/demo/runs/S01").status_code == 202  # the gate reopens


def test_reset_waits_for_in_flight_work_and_fails_cleanly_on_timeout(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    with get_sessionmaker()() as s:
        before = s.scalar(select(RunRow.id).order_by(RunRow.id.desc()))
    monkeypatch.setattr(seed_mod, "RESET_WAIT_S", 0.2)
    with _busy():
        resp = api.post("/api/demo/reset")
        assert (resp.status_code, resp.json()["code"]) == (409, "reset_timeout")
        with get_sessionmaker()() as s:  # nothing was dropped
            assert s.scalar(select(RunRow.id).order_by(RunRow.id.desc())) == before
        assert api.post("/api/demo/runs/S01").status_code == 202  # not left locked
    assert runner.wait_idle(30)


def test_wait_idle_sees_work_started_after_it_was_called() -> None:
    """Regression: `wait_idle()` only waited for a snapshot of the queued futures."""
    started = threading.Event()
    result: list[bool] = []

    def waiter() -> None:
        started.wait(5)
        result.append(runner.wait_idle(0.3))

    with _busy():
        t = threading.Thread(target=waiter)
        t.start()
        started.set()
        t.join(5)
    assert result == [False]
    assert runner.wait_idle(5)


# --- B06/B08: model-call audit events ------------------------------------------------------------


def _meta(prompt_id: str, latency: int, tokens_in: int, tokens_out: int) -> CallMeta:
    return CallMeta(
        provider="fake",
        model="fake-light",
        prompt_id=prompt_id,
        prompt_version="v1",
        latency_ms=latency,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
    )


class LiveFake(FakeClient):
    """The offline reader, posing as a live provider that suggests lines and polishes."""

    is_live = True

    def map_lines(self, inv: Any, po: PurchaseOrder) -> tuple[list[LineGroup], CallMeta]:
        return [], _meta("map_lines", 21, 300, 12)

    def polish(self, summary: str, facts: dict[str, Any]) -> tuple[str, CallMeta]:
        return f"In short: {summary}", _meta("polish_explanation", 34, 180, 60)


def test_line_mapping_and_polish_calls_are_logged(api: TestClient) -> None:
    """Regression: map_lines left no event, and polish logged only accepted rewrites without
    prompt version, latency, tokens or cache status."""
    client = LiveFake(get_settings())
    run_id = runner.submit(_pdf("S14"), "S14.pdf", background=False, client=client, polish=True)
    with get_sessionmaker()() as s:
        logged = [e for e in events.events_after(s, run_id) if e.type == "stage.log"]
    calls = {e.data["llm_call"]["kind"]: e for e in logged if e.data and "llm_call" in e.data}
    assert set(calls) >= {"map_lines", "polish"}
    mapping, polish = calls["map_lines"], calls["polish"]
    assert mapping.stage == StageName.match_lines and polish.stage == StageName.explain_route
    assert mapping.data["llm_call"] == {
        "kind": "map_lines", "provider": "fake", "model": "fake-light", "prompt": "map_lines@v1",
        "latency_ms": 21, "tokens_in": 300, "tokens_out": 12, "cached": False, "attempts": 1,
        "accepted_groups": 0,
    }  # fmt: skip
    p = polish.data["llm_call"]
    assert (p["prompt"], p["latency_ms"], p["tokens_in"], p["tokens_out"], p["cached"]) == (
        "polish_explanation@v1", 34, 180, 60, False,
    )  # fmt: skip
    assert p["accepted"] is True and "polish_explanation@v1" in (polish.message or "")


# --- B08: SSE replay -----------------------------------------------------------------------------


def test_replay_from_zero_streams_the_whole_reviewed_history(api: TestClient) -> None:
    """Regression: replaying a reviewed run from after=0 closed on the first terminal event."""
    run = _demo(api, "S04")
    resp = _review(api, run["id"], action="confirm_po", po_number="KF-PO-0151",
                   fields_verified=True, note="Matches the GRN")  # fmt: skip
    assert resp.status_code == 200
    wait_run(api, run["id"])
    types = [e["type"] for e in replay(api, run["id"], after=0)]
    assert types.count("run.awaiting_review") == 1
    assert types.index("run.awaiting_review") < types.index("review.recorded")
    assert types.index("review.recorded") < types.index("run.resumed")
    assert types.count("decision.made") == 2 and types[-1] == "run.completed"


# --- B08: event sequence collisions --------------------------------------------------------------


def test_event_seq_collision_on_flush_is_retried(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: `_insert()` flushed before the try around commit, so a clash on
    (run_id, seq) raised instead of being retried."""
    run = _demo(api, "S01")
    real = events._insert
    clashes = 0

    def clashing(session: Any, run_id: int, *args: Any) -> RunEventRow:
        nonlocal clashes
        if clashes == 0:
            clashes += 1
            session.add(RunEventRow(run_id=run_id, seq=1, ts=clock.now(), type="stage.log"))
            session.flush()  # seq 1 is taken: IntegrityError here
        return real(session, run_id, *args)

    monkeypatch.setattr(events, "_insert", clashing)
    ev = events.emit(run["id"], "stage.log", message="after a clash")
    assert clashes == 1 and ev.seq > 1 and ev.message == "after a clash"

    def always(session: Any, run_id: int, *args: Any) -> RunEventRow:
        raise IntegrityError("insert", {}, Exception("seq taken"))

    monkeypatch.setattr(events, "_insert", always)
    with pytest.raises(IntegrityError):
        events.emit(run["id"], "stage.log", message="gives up after MAX_ATTEMPTS")


# --- B07/B08: policy preview ---------------------------------------------------------------------


def test_preview_recomputes_po_inference_under_the_proposed_policy(
    api: TestClient, seeded_db: Path
) -> None:
    """Regression: raising min_score above the inferred PO's score still gave PO_INFERRED,
    because PO selection was computed under the old policy."""
    run = _demo(api, "S04")
    current = active_policy()
    strict = current.with_overrides({"po_inference": {"min_score": 0.99}})
    with get_sessionmaker()() as s:
        row = s.get(RunRow, run["id"])
        assert row is not None
        assert _decide(s, row, current).outcome == Outcome.HOLD
        assert "PO_INFERRED" in _decide(s, row, current).reasons
        reasons = _decide(s, row, strict).reasons
    assert "PO_INFERRED" not in reasons and "PO_MISSING" in reasons


def test_preview_po_inference_leaves_out_the_runs_own_billing(api: TestClient) -> None:
    """Regression: PO inference counted the run's own billing when re-checking it."""
    run = _demo(api, "S04")
    resolve = next(s for s in run["stages"] if s["name"] == "resolve_po")
    before = resolve["detail"]["candidates"][0]
    resp = _review(api, run["id"], action="confirm_po", po_number="KF-PO-0151",
                   fields_verified=True, note="Matches the GRN")  # fmt: skip
    assert resp.status_code == 200
    assert wait_run(api, run["id"])["final_outcome"] == "APPROVE"
    with get_sessionmaker()() as s:
        row = s.get(RunRow, run["id"])
        assert row is not None and row.extraction is not None
        ctx = build_context(
            s,
            InvoiceExtraction.model_validate(row.extraction),
            policy=active_policy(),
            today=clock.today(),
            overrides=ReviewOverrides(),
            file_sha256=row.document.sha256,
            run_id=row.id,
        )
    top = next(c for c in ctx.po_candidates if c.po_number == before["po_number"])
    assert top.score == before["score"]
    assert ctx.po is not None and ctx.po_method == "inferred"
