"""Model output (RawInvoice), normalised extraction and reader output shapes."""

from __future__ import annotations

from datetime import date
from typing import Literal

from app.enums import ConfidenceLevel, DocKind, DocType
from app.models.common import Dec, Model, Money, StrictModel, UtcDatetime

# --- What the model returns: every value is a string exactly as printed, or null. ---


class RawLine(StrictModel):
    description: str
    item_code: str | None
    hsn_sac: str | None
    quantity: str | None
    uom: str | None
    unit_price: str | None
    amount: str | None
    tax_rate: str | None


class RawTaxLine(StrictModel):
    tax_type: Literal["CGST", "SGST", "IGST", "UTGST", "CESS", "OTHER"]
    rate: str | None
    amount: str


class RawCharge(StrictModel):
    label: str
    amount: str


class RawInvoice(StrictModel):
    document_type: DocType
    document_title: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    supplier_name: str | None
    supplier_gstin: str | None
    supplier_address: str | None
    supplier_phone: str | None
    supplier_email: str | None
    buyer_name: str | None
    buyer_gstin: str | None
    place_of_supply: str | None
    po_reference: str | None
    currency: str | None
    line_items: list[RawLine]
    subtotal: str | None
    tax_lines: list[RawTaxLine]
    other_charges: list[RawCharge]
    round_off: str | None
    total: str | None
    amount_in_words: str | None
    prices_include_tax: bool | None
    bank_account_name: str | None
    bank_account_number: str | None
    bank_ifsc: str | None
    bank_name: str | None
    annotations: list[str]
    legibility: Literal["clear", "partly_legible", "poor"]


# --- Normalised extraction ---


class BBox(Model):
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class FieldValue(Model):
    value: str | Dec | date | None
    raw: str | None
    confidence: float
    level: ConfidenceLevel
    grounded: Literal["exact", "fuzzy", "none", "unavailable"]
    validators: list[str]
    bbox: list[BBox]
    notes: list[str]


class LineItem(Model):
    index: int
    description: str
    item_code: str | None
    hsn_sac: str | None
    quantity: Dec | None
    uom: str | None
    unit_price: Money | None
    amount: Money | None
    tax_rate_pct: Dec | None
    taxable_amount: Money | None
    bbox: list[BBox]


class TaxSummary(Model):
    cgst: Money
    sgst: Money
    igst: Money
    other: Money
    total_tax: Money
    rates_pct: list[Dec]
    kind: Literal["intra", "inter", "none", "mixed"]


class ExtractionMeta(Model):
    provider: str
    model: str
    prompt_id: str
    prompt_version: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    cached: bool
    cached_at: UtcDatetime | None
    raw: RawInvoice


class InvoiceExtraction(Model):
    doc_type: DocType
    doc_kind: DocKind
    legibility: str
    invoice_number: FieldValue
    invoice_number_canonical: str | None
    invoice_date: FieldValue
    due_date: FieldValue
    supplier_name: FieldValue
    supplier_gstin: FieldValue
    supplier_phone: FieldValue
    buyer_name: FieldValue
    buyer_gstin: FieldValue
    place_of_supply: FieldValue
    po_reference: FieldValue
    po_reference_canonical: str | None
    currency: str
    line_items: list[LineItem]
    subtotal: FieldValue
    tax: TaxSummary
    other_charges_total: Money
    round_off: FieldValue
    total: FieldValue
    amount_in_words: FieldValue
    prices_include_tax: bool
    bank_account_number: FieldValue
    bank_ifsc: FieldValue
    bank_name: FieldValue
    annotations: list[str]
    meta: ExtractionMeta


# --- Reader output (produced by ingest/reader.py) ---


class Word(Model):
    text: str
    bbox: BBox
    conf: float | None


class PageRead(Model):
    index: int
    width_pt: float
    height_pt: float
    kind: DocKind
    text: str
    words: list[Word]
    ocr_used: bool
    ocr_mean_conf: float | None


class DocumentRead(Model):
    sha256: str
    pages: list[PageRead]
    doc_kind: DocKind
    ocr_available: bool
    page_count: int
