"""Reference data: vendors and purchase orders."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, ERROR_RESPONSES, not_found
from app.api.views import run_summary, vendor_names
from app.extract.normalize import mask_account
from app.models.api import PurchaseOrderDetail, PurchaseOrderOut, VendorOut
from app.models.reference import GoodsReceipt
from app.orm import GoodsReceiptRow, PurchaseOrderRow, RunRow, VendorRow
from app.reference.ledger import Ledger
from app.reference.loader import po_from_row, vendor_from_row
from app.rules.base import q2

router = APIRouter(tags=["reference"], responses=ERROR_RESPONSES)
HUNDRED = Decimal(100)


@router.get("/vendors", response_model=list[VendorOut])
def list_vendors(db: DB) -> list[VendorOut]:
    open_pos = dict(
        db.execute(
            select(PurchaseOrderRow.vendor_id, func.count())
            .where(PurchaseOrderRow.status == "open")
            .group_by(PurchaseOrderRow.vendor_id)
        ).all()
    )
    invoices = dict(
        db.execute(
            select(RunRow.vendor_id, func.count())
            .where(RunRow.vendor_id.is_not(None))
            .group_by(RunRow.vendor_id)
        ).all()
    )
    out = []
    for row in db.scalars(select(VendorRow).order_by(VendorRow.vendor_id)):
        v = vendor_from_row(row)
        out.append(
            VendorOut(
                **v.model_dump() | {"bank_account_number": mask_account(v.bank_account_number)},
                open_po_count=open_pos.get(v.vendor_id, 0),
                invoice_count=invoices.get(v.vendor_id, 0),
            )
        )
    return out


def _po_out(db: DB, row: PurchaseOrderRow) -> PurchaseOrderOut:
    po = po_from_row(row)
    balances = Ledger(db).balance_map(po.po_number)
    ordered = sum((q2(ln.quantity * ln.unit_price) for ln in po.lines), Decimal())
    billed = sum(
        (
            q2(balances[ln.line_no].billed * ln.unit_price)
            for ln in po.lines
            if ln.line_no in balances
        ),
        Decimal(),
    )
    pct = q2(billed / ordered * HUNDRED) if ordered else Decimal("0.00")
    return PurchaseOrderOut(
        **po.model_dump(), ordered_value=ordered, billed_value=billed, pct_billed=pct
    )


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    db: DB,
    vendor_id: str | None = None,
    status: Literal["open", "closed", "cancelled"] | None = None,
) -> list[PurchaseOrderOut]:
    stmt = select(PurchaseOrderRow).order_by(PurchaseOrderRow.po_number)
    if vendor_id:
        stmt = stmt.where(PurchaseOrderRow.vendor_id == vendor_id)
    if status:
        stmt = stmt.where(PurchaseOrderRow.status == status)
    return [_po_out(db, row) for row in db.scalars(stmt)]


@router.get("/purchase-orders/{po}", response_model=PurchaseOrderDetail)
def get_purchase_order(po: str, db: DB) -> PurchaseOrderDetail:
    row = db.get(PurchaseOrderRow, po)
    if row is None:
        raise not_found(f"Purchase order {po}")
    grns = [
        GoodsReceipt(
            grn_number=g.grn_number,
            po_number=g.po_number,
            line_no=g.line_no,
            quantity_received=g.quantity_received,
            received_date=g.received_date,
        )
        for g in db.scalars(
            select(GoodsReceiptRow)
            .where(GoodsReceiptRow.po_number == po)
            .order_by(GoodsReceiptRow.received_date, GoodsReceiptRow.grn_number)
        )
    ]
    names = vendor_names(db)
    runs = db.scalars(select(RunRow).where(RunRow.po_number == po).order_by(RunRow.created_at))
    return PurchaseOrderDetail(
        po=po_from_row(row),
        balances=Ledger(db).balances(po),
        grns=grns,
        runs=[run_summary(r, names) for r in runs],
    )
