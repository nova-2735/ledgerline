"""Seeded history (SCENARIOS §6): 24 runs through the real pipeline, reviews applied."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app import db
from app.demo.invoice import load_specs, load_world
from app.enums import Outcome, RunSource, RunStatus
from app.orm import RunRow
from app.reference.ledger import Ledger
from tests.helpers.world import expectations, final_outcome


def _runs() -> dict[str, RunRow]:
    with db.get_sessionmaker()() as s:
        rows = list(s.scalars(select(RunRow).order_by(RunRow.id)))
        for r in rows:
            _ = r.review_actions
        return {r.scenario_id or "": r for r in rows}


def test_seed_outcomes(seeded_db: Path) -> None:
    runs = _runs()
    assert len(runs) == 24
    specs = {s.id: s for s in load_specs(load_world()) if s.kind == "history"}
    assert set(runs) == set(specs)
    for doc_id, run in runs.items():
        exp = expectations()[doc_id]
        first = run.decision_history[0]
        allowed = set(exp["required"]) | set(exp.get("allowed", []))
        if doc_id == "H13" and first["outcome"] == "HOLD":
            assert first["reasons"] == ["FIELD_LOW_CONFIDENCE"]
        else:
            assert (first["outcome"], first["route"]) == (exp["outcome"], exp["route"]), doc_id
            assert set(exp["required"]) <= set(first["reasons"]), doc_id
            assert set(first["reasons"]) <= allowed, (doc_id, first["reasons"])
        want = final_outcome(specs[doc_id])
        assert run.final_outcome == (want.value if want else None), doc_id
        assert run.source == RunSource.seed.value


def test_seed_state(seeded_db: Path) -> None:
    runs = _runs()
    h23 = runs["H23"]
    assert h23.status == RunStatus.awaiting_review.value
    assert (h23.outcome, h23.route, h23.primary_reason) == (
        "HOLD",
        "receiving",
        "GOODS_NOT_RECEIVED",
    )
    assert [r for r in runs.values() if r.status == RunStatus.awaiting_review.value] == [h23]
    h11 = runs["H11"]
    assert h11.final_outcome == Outcome.APPROVE.value and len(h11.decision_history) == 2
    assert h11.review_actions[0].reviewer == "Priya Nair (AP)"
    assert runs["H15"].final_outcome == Outcome.RETURN.value
    assert runs["H19"].final_outcome == Outcome.REJECT.value
    assert runs["H04"].created_at.date().isoformat() == "2026-09-04"
    with db.get_sessionmaker()() as s:
        ledger = Ledger(s)
        b119 = ledger.balance_map("KF-PO-0119")[1]
        assert (b119.billed, b119.received) == (Decimal(60), Decimal(90))
        assert all(b.remaining_to_bill == 0 for b in ledger.balances("KF-PO-0126"))
