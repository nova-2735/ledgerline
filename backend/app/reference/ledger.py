"""PO ledger: what each PO line has been received and billed (RULES §7).

`billed` counts only invoices whose final outcome is APPROVE. `invoice_ledger` also holds the
other finished runs, which the duplicate checks compare against.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.enums import MatchType, Outcome
from app.models.common import Dec, Money
from app.models.reference import POLineBalance
from app.orm import GoodsReceiptRow, InvoiceLedgerRow, PurchaseOrderRow, RunRow

# A returned invoice is expected to be re-issued and a rejected one was never payable, so
# neither counts as an earlier invoice for the duplicate checks (RULES §1.6).
NOT_COMPARABLE = frozenset({Outcome.REJECT.value, Outcome.RETURN.value})


class BilledLine(BaseModel):
    po_line_no: int
    qty: Dec
    amount: Money


class LedgerEntry(BaseModel):
    run_id: int
    vendor_id: str | None
    invoice_number: str | None
    invoice_number_canonical: str | None
    invoice_date: date | None
    total: Money | None
    po_number: str | None
    file_sha256: str
    final_outcome: Outcome | None
    billed_lines: list[BilledLine] = []
    display_id: str | None = None  # filled on read, for evidence
    finished_at: datetime | None = None


def _entry(row: InvoiceLedgerRow, run: RunRow | None = None) -> LedgerEntry:
    return LedgerEntry(
        run_id=row.run_id,
        vendor_id=row.vendor_id,
        invoice_number=row.invoice_number,
        invoice_number_canonical=row.invoice_number_canonical,
        invoice_date=row.invoice_date,
        total=row.total,
        po_number=row.po_number,
        file_sha256=row.file_sha256,
        final_outcome=Outcome(row.final_outcome) if row.final_outcome else None,
        billed_lines=[BilledLine.model_validate(b) for b in row.billed_lines or []],
        display_id=run.display_id if run else None,
        finished_at=run.finished_at if run else None,
    )


def _billed_json(rows: list[BilledLine]) -> list[dict[str, Any]]:
    return [b.model_dump(mode="json") for b in rows]


class Ledger:
    """Balances and ledger rows, read from the database through `session`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _read(self, row: InvoiceLedgerRow) -> LedgerEntry:
        return _entry(row, self.session.get(RunRow, row.run_id))

    # --- balances ---------------------------------------------------------------------------

    def balances(self, po_number: str, exclude_run_id: int | None = None) -> list[POLineBalance]:
        """One balance per PO line; empty when the PO does not exist. `exclude_run_id` leaves one
        run's own billing out (re-evaluating a finished run)."""
        po = self.session.get(PurchaseOrderRow, po_number)
        if po is None:
            return []
        received: dict[int, Decimal] = defaultdict(Decimal)
        for grn in self.session.scalars(
            select(GoodsReceiptRow).where(GoodsReceiptRow.po_number == po_number)
        ):
            received[grn.line_no] += grn.quantity_received

        billed: dict[int, Decimal] = defaultdict(Decimal)
        invoices: dict[int, list[int]] = defaultdict(list)
        approved = select(InvoiceLedgerRow).where(
            InvoiceLedgerRow.po_number == po_number,
            InvoiceLedgerRow.final_outcome == Outcome.APPROVE.value,
        )
        for row in self.session.scalars(approved.order_by(InvoiceLedgerRow.run_id)):
            if row.run_id == exclude_run_id:
                continue
            for b in _entry(row).billed_lines:
                billed[b.po_line_no] += b.qty
                if row.run_id not in invoices[b.po_line_no]:
                    invoices[b.po_line_no].append(row.run_id)

        three_way = po.match_type == MatchType.three_way.value
        out = []
        for ln in po.lines:
            got, done = received[ln.line_no], billed[ln.line_no]
            out.append(
                POLineBalance(
                    po_number=po_number,
                    line_no=ln.line_no,
                    ordered=ln.quantity,
                    received=got,
                    billed=done,
                    remaining_to_bill=ln.quantity - done,
                    received_unbilled=(got - done) if three_way else None,
                    invoices=invoices[ln.line_no],
                )
            )
        return out

    def balance_map(
        self, po_number: str, exclude_run_id: int | None = None
    ) -> dict[int, POLineBalance]:
        return {b.line_no: b for b in self.balances(po_number, exclude_run_id)}

    # --- writing ----------------------------------------------------------------------------

    def upsert_entry(self, entry: LedgerEntry) -> None:
        """Create or replace the ledger row for a finished run."""
        row = self.session.get(InvoiceLedgerRow, entry.run_id)
        values = entry.model_dump(exclude={"display_id", "finished_at"})
        values["final_outcome"] = entry.final_outcome.value if entry.final_outcome else None
        values["billed_lines"] = _billed_json(entry.billed_lines)
        if row is None:
            self.session.add(InvoiceLedgerRow(**values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self.session.flush()

    def record_billing(self, run_id: int, rows: list[BilledLine]) -> None:
        """Mark a run as finally approved and record the PO lines it bills."""
        row = self.session.get(InvoiceLedgerRow, run_id)
        if row is None:
            raise LookupError(f"no ledger entry for run {run_id}")
        row.final_outcome = Outcome.APPROVE.value
        row.billed_lines = _billed_json(rows)
        self.session.flush()

    def set_outcome(self, run_id: int, outcome: Outcome | None) -> None:
        """Change a run's final outcome; anything but APPROVE stops it counting as billed."""
        row = self.session.get(InvoiceLedgerRow, run_id)
        if row is None:
            raise LookupError(f"no ledger entry for run {run_id}")
        row.final_outcome = outcome.value if outcome else None
        if outcome != Outcome.APPROVE:
            row.billed_lines = []
        self.session.flush()

    # --- reading rows for duplicate checks --------------------------------------------------

    def ledger_rows_for_vendor(
        self,
        vendor_id: str,
        window_days: int,
        *,
        around: date | None = None,
        exclude_run_id: int | None = None,
    ) -> list[LedgerEntry]:
        """Comparable earlier invoices of a vendor whose invoice date is within `window_days` of
        `around` (default today). Rows without a date are kept; REJECT/RETURN rows are not."""
        centre = around or clock.today()
        lo, hi = centre - timedelta(days=window_days), centre + timedelta(days=window_days)
        stmt = select(InvoiceLedgerRow).where(InvoiceLedgerRow.vendor_id == vendor_id)
        out = []
        for row in self.session.scalars(stmt.order_by(InvoiceLedgerRow.run_id)):
            if row.run_id == exclude_run_id or row.final_outcome in NOT_COMPARABLE:
                continue
            if row.invoice_date is not None and not lo <= row.invoice_date <= hi:
                continue
            out.append(self._read(row))
        return out

    def rows_for_file(self, sha256: str, *, exclude_run_id: int | None = None) -> list[LedgerEntry]:
        """Comparable earlier runs of the same file (any vendor)."""
        stmt = select(InvoiceLedgerRow).where(InvoiceLedgerRow.file_sha256 == sha256)
        return [
            self._read(r)
            for r in self.session.scalars(stmt.order_by(InvoiceLedgerRow.run_id))
            if r.run_id != exclude_run_id and r.final_outcome not in NOT_COMPARABLE
        ]

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(InvoiceLedgerRow)) or 0)
