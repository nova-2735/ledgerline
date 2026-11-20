"""Reference data: company, vendor master, purchase orders, goods receipts."""

from __future__ import annotations

from datetime import date
from typing import Literal

from app.enums import MatchType
from app.models.common import Dec, Model, Money


class Company(Model):
    name: str
    gstin: str
    state_code: str
    address: str


class Vendor(Model):
    vendor_id: str
    legal_name: str
    aliases: list[str]
    gstin: str
    pan: str
    state_code: str
    address: str
    city: str
    email: str
    phone_on_file: str
    bank_name: str
    bank_account_number: str
    bank_ifsc: str
    status: Literal["active", "blocked"]
    block_reason: str | None
    payment_terms_days: int
    category: str


class POLine(Model):
    line_no: int
    item_code: str
    description: str
    quantity: Dec
    uom: str
    unit_price: Money
    tax_rate_pct: Dec
    hsn_sac: str
    gl_account: str


class PurchaseOrder(Model):
    po_number: str
    vendor_id: str
    po_date: date
    status: Literal["open", "closed", "cancelled"]
    currency: str = "INR"
    match_type: MatchType
    buyer_name: str
    cost_center: str
    lines: list[POLine]


class GoodsReceipt(Model):
    grn_number: str
    po_number: str
    line_no: int
    quantity_received: Dec
    received_date: date


class POLineBalance(Model):
    po_number: str
    line_no: int
    ordered: Dec
    received: Dec
    billed: Dec
    remaining_to_bill: Dec
    received_unbilled: Dec | None
    invoices: list[int]
