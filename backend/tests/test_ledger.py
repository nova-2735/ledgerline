from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.enums import Outcome
from app.reference.ledger import BilledLine, Ledger, LedgerEntry
from tests.helpers.world import SeededWorld


def test_0119_split_billing(seeded_world: SeededWorld) -> None:
    [bal] = Ledger(seeded_world.session).balances("KF-PO-0119")
    assert (bal.ordered, bal.received, bal.billed) == (Decimal(100), Decimal(90), Decimal(60))
    assert bal.remaining_to_bill == Decimal(40)
    assert bal.received_unbilled == Decimal(30)
    runs = seeded_world.run_ids
    assert bal.invoices == sorted([runs["H01"], runs["H02"]])


def test_0126_fully_billed(seeded_world: SeededWorld) -> None:
    [bal] = Ledger(seeded_world.session).balances("KF-PO-0126")
    assert bal.billed == Decimal(1500)
    assert bal.remaining_to_bill == Decimal(0)
    assert bal.received_unbilled == Decimal(0)


def test_two_way_has_no_received_unbilled(seeded_world: SeededWorld) -> None:
    [bal] = Ledger(seeded_world.session).balances("KF-PO-0137")
    assert bal.received_unbilled is None
    assert bal.billed == 0 and bal.remaining_to_bill == Decimal(12)


def test_untouched_and_unknown_po(seeded_world: SeededWorld) -> None:
    ledger = Ledger(seeded_world.session)
    bals = ledger.balances("KF-PO-0151")
    assert [(b.line_no, b.received, b.billed) for b in bals] == [
        (1, Decimal(10), Decimal(0)),
        (2, Decimal(20), Decimal(0)),
    ]
    assert ledger.balances("KF-PO-9999") == []


def test_seed_skips_non_approved_history(seeded_world: SeededWorld) -> None:
    assert {"H15", "H19", "H23"}.isdisjoint(seeded_world.run_ids)
    assert {"H11", "H13", "H21"} <= set(seeded_world.run_ids)
    assert len(seeded_world.run_ids) == 21


def _entry(run_id: int, outcome: Outcome | None, **kw: Any) -> LedgerEntry:
    base: dict[str, Any] = {
        "run_id": run_id,
        "vendor_id": "V003",
        "invoice_number": "AIS/26-27/1188",
        "invoice_number_canonical": "26271188",
        "invoice_date": date(2026, 11, 15),
        "total": "85550.00",
        "po_number": "KF-PO-0119",
        "file_sha256": "f" * 64,
        "final_outcome": outcome,
    }
    return LedgerEntry.model_validate(base | kw)


def test_record_billing_moves_balances(seeded_world: SeededWorld) -> None:
    ledger = Ledger(seeded_world.session)
    run_id = seeded_world.run_ids["H18"]  # an existing run, so the foreign key holds
    ledger.upsert_entry(_entry(run_id, None))
    ledger.record_billing(run_id, [BilledLine(po_line_no=1, qty=Decimal(30), amount="43500.00")])
    [bal] = ledger.balances("KF-PO-0119")
    assert bal.billed == Decimal(90) and bal.received_unbilled == Decimal(0)
    assert run_id in bal.invoices

    ledger.set_outcome(run_id, Outcome.REJECT)
    [bal] = ledger.balances("KF-PO-0119")
    assert bal.billed == Decimal(60)


def test_record_billing_needs_an_entry(seeded_world: SeededWorld) -> None:
    with pytest.raises(LookupError):
        Ledger(seeded_world.session).record_billing(10_000, [])


def test_rows_for_vendor_window_and_exclusions(seeded_world: SeededWorld) -> None:
    ledger = Ledger(seeded_world.session)
    numbers = {r.invoice_number for r in ledger.ledger_rows_for_vendor("V001", 365)}
    assert {"SPI/26-27/0187", "SPI/26-27/0198", "SPI/26-27/0121"} <= numbers

    recent = ledger.ledger_rows_for_vendor("V001", 50, around=date(2026, 11, 17))
    assert {r.invoice_number for r in recent} == {"SPI/26-27/0187", "SPI/26-27/0198"}

    h03 = seeded_world.run_ids["H03"]
    kept = ledger.ledger_rows_for_vendor("V001", 365, exclude_run_id=h03)
    assert h03 not in {r.run_id for r in kept}
    ledger.set_outcome(h03, Outcome.RETURN)
    assert h03 not in {r.run_id for r in ledger.ledger_rows_for_vendor("V001", 365)}


def test_rows_for_file(seeded_world: SeededWorld) -> None:
    ledger = Ledger(seeded_world.session)
    h14 = seeded_world.run_ids["H14"]
    row = next(r for r in ledger.ledger_rows_for_vendor("V001", 365) if r.run_id == h14)
    assert [r.run_id for r in ledger.rows_for_file(row.file_sha256)] == [h14]
    assert ledger.rows_for_file(row.file_sha256, exclude_run_id=h14) == []
