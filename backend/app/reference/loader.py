"""Load the procurement spreadsheet (company.json + CSVs, CONTRACTS §8) into the database."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.reference import Company, GoodsReceipt, POLine, PurchaseOrder, Vendor
from app.orm import CompanyRow, GoodsReceiptRow, POLineRow, PurchaseOrderRow, VendorRow

REFERENCE_FILES = ("company.json", "vendors.csv", "purchase_orders.csv", "goods_receipts.csv")

_PO_HEADER = (
    "po_number",
    "vendor_id",
    "po_date",
    "status",
    "currency",
    "match_type",
    "buyer_name",
    "cost_center",
)


def _reference_dir(data_dir: Path) -> Path:
    """Accept either the generated world root or its `reference/` folder."""
    nested = data_dir / "reference"
    return nested if (nested / "vendors.csv").exists() else data_dir


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_reference(
    data_dir: Path,
) -> tuple[Company, list[Vendor], list[PurchaseOrder], list[GoodsReceipt]]:
    """Parse and validate the reference files without touching the database."""
    ref = _reference_dir(data_dir)
    missing = [name for name in REFERENCE_FILES if not (ref / name).exists()]
    if missing:
        raise FileNotFoundError(f"reference data missing in {ref}: {', '.join(missing)}")

    company = Company.model_validate(json.loads((ref / "company.json").read_text("utf-8")))

    vendors = []
    for row in _rows(ref / "vendors.csv"):
        data: dict[str, Any] = dict(row)
        data["aliases"] = [a.strip() for a in row["aliases"].split(";") if a.strip()]
        data["block_reason"] = row["block_reason"] or None
        vendors.append(Vendor.model_validate(data))

    headers: dict[str, dict[str, str]] = {}
    lines: dict[str, list[POLine]] = defaultdict(list)
    for row in _rows(ref / "purchase_orders.csv"):
        po_number = row["po_number"]
        header = {k: row[k] for k in _PO_HEADER}
        if po_number in headers and headers[po_number] != header:
            raise ValueError(f"{po_number}: header fields differ between its line rows")
        headers[po_number] = header
        lines[po_number].append(
            POLine.model_validate({k: v for k, v in row.items() if k not in _PO_HEADER})
        )
    pos = [
        PurchaseOrder.model_validate(
            {**headers[n], "lines": sorted(lines[n], key=lambda ln: ln.line_no)}
        )
        for n in headers
    ]

    grns = [GoodsReceipt.model_validate(row) for row in _rows(ref / "goods_receipts.csv")]
    return company, vendors, pos, grns


def load_reference(session: Session, data_dir: Path) -> dict[str, int]:
    """Replace the reference tables with the files in `data_dir` (truncate + insert).

    Idempotent: loading the same files twice gives the same rows. Returns row counts.
    """
    company, vendors, pos, grns = read_reference(data_dir)
    for table in (GoodsReceiptRow, POLineRow, PurchaseOrderRow, VendorRow, CompanyRow):
        session.execute(delete(table))
    session.flush()

    session.add(CompanyRow(id=1, **company.model_dump()))
    session.add_all(VendorRow(**v.model_dump()) for v in vendors)
    session.flush()
    for po in pos:
        header = po.model_dump(exclude={"lines"})
        header["match_type"] = po.match_type.value
        session.add(
            PurchaseOrderRow(**header, lines=[POLineRow(**ln.model_dump()) for ln in po.lines])
        )
    session.flush()
    session.add_all(GoodsReceiptRow(**g.model_dump()) for g in grns)
    session.commit()
    return {
        "company": 1,
        "vendors": len(vendors),
        "purchase_orders": len(pos),
        "po_lines": sum(len(po.lines) for po in pos),
        "goods_receipts": len(grns),
    }


# --- read back as domain models ----------------------------------------------------------------


def company_from_row(row: CompanyRow) -> Company:
    return Company(name=row.name, gstin=row.gstin, state_code=row.state_code, address=row.address)


def vendor_from_row(row: VendorRow) -> Vendor:
    return Vendor.model_validate({c.key: getattr(row, c.key) for c in VendorRow.__table__.columns})


def po_from_row(row: PurchaseOrderRow) -> PurchaseOrder:
    header = {c.key: getattr(row, c.key) for c in PurchaseOrderRow.__table__.columns}
    lines = [
        POLine.model_validate(
            {
                c.key: getattr(ln, c.key)
                for c in POLineRow.__table__.columns
                if c.key not in ("id", "po_number")
            }
        )
        for ln in row.lines
    ]
    return PurchaseOrder.model_validate({**header, "lines": lines})
