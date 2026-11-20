"""Reference data: vendors and purchase orders."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from app.api.deps import ERROR_RESPONSES, not_implemented
from app.models.api import PurchaseOrderDetail, PurchaseOrderOut, VendorOut

router = APIRouter(tags=["reference"], responses=ERROR_RESPONSES)


@router.get("/vendors", response_model=list[VendorOut])
def list_vendors() -> list[VendorOut]:
    not_implemented()


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    vendor_id: str | None = None,
    status: Literal["open", "closed", "cancelled"] | None = None,
) -> list[PurchaseOrderOut]:
    not_implemented()


@router.get("/purchase-orders/{po}", response_model=PurchaseOrderDetail)
def get_purchase_order(po: str) -> PurchaseOrderDetail:
    not_implemented()
