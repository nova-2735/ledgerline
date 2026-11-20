"""Small builders for rule tests: an S01-like extraction and a hand-made context (no database)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import cache
from typing import Any

from app.decide.policy import Policy, load_policy
from app.demo.invoice import World, load_world
from app.demo.money import format_indian
from app.enums import DocKind, MatchType
from app.extract.extractor import normalise
from app.models.checks import CheckResult
from app.models.extraction import DocumentRead, ExtractionMeta, InvoiceExtraction, RawInvoice
from app.models.reference import GoodsReceipt, POLineBalance
from app.reference.ledger import BilledLine, LedgerEntry
from app.reference.vendors import VendorMatch
from app.rules.base import POMethod, ReviewOverrides, RuleContext

TODAY = date(2026, 11, 20)


@cache
def world() -> World:
    return load_world()


@cache
def policy() -> Policy:
    return load_policy()


def money(value: str | Decimal) -> str:
    return format_indian(Decimal(value))


def line(
    desc: str,
    qty: str,
    rate: str,
    *,
    code: str | None = None,
    tax: str | None = "18%",
    amount: str | None = None,
    uom: str = "Nos",
    hsn: str = "4819",
) -> dict[str, Any]:
    value = amount if amount is not None else money(Decimal(qty) * Decimal(rate))
    return {
        "description": desc,
        "item_code": code,
        "hsn_sac": hsn,
        "quantity": qty,
        "uom": uom,
        "unit_price": money(rate),
        "amount": value,
        "tax_rate": tax,
    }


S01_LINES = [
    line("Corrugated shipper box 450x300x250 mm, 5-ply", "2000", "38.50", code="PKG-CB-0450"),
    line("BOPP packing tape 48 mm x 65 m, brown", "300", "72.00", code="PKG-TP-0048", uom="Roll"),
]


def raw_s01(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "document_type": "tax_invoice",
        "document_title": "TAX INVOICE",
        "invoice_number": "SPI/26-27/0214",
        "invoice_date": "12/11/2026",
        "due_date": None,
        "supplier_name": "Sharma Packaging Industries",
        "supplier_gstin": "27AAKFS2231P1ZS",
        "supplier_address": "Plot 47, Bhosari MIDC, Pune",
        "supplier_phone": "+91 20 2712 4455",
        "supplier_email": "accounts@sharmapackaging.example",
        "buyer_name": "Kestrel Foods Pvt. Ltd.",
        "buyer_gstin": "29AAJCK4417M1Z1",
        "place_of_supply": "Karnataka (29)",
        "po_reference": "KF-PO-0142",
        "currency": "INR",
        "line_items": S01_LINES,
        "subtotal": "98,600.00",
        "tax_lines": [{"tax_type": "IGST", "rate": "18%", "amount": "17,748.00"}],
        "other_charges": [],
        "round_off": None,
        "total": "1,16,348.00",
        "amount_in_words": "Rupees One Lakh Sixteen Thousand Three Hundred Forty Eight Only",
        "prices_include_tax": False,
        "bank_account_name": None,
        "bank_account_number": "50200012345678",
        "bank_ifsc": "HDFC0000123",
        "bank_name": "HDFC Bank",
        "annotations": [],
        "legibility": "clear",
    }
    raw.update(overrides)
    return raw


def make_extraction(**overrides: Any) -> InvoiceExtraction:
    """S01 as transcribed, with RawInvoice fields overridden; normalised by the real code."""
    raw = RawInvoice.model_validate(raw_s01(**overrides))
    doc = DocumentRead(
        sha256="0" * 64, pages=[], doc_kind=DocKind.digital, ocr_available=False, page_count=1
    )
    meta = ExtractionMeta(
        provider="fake",
        model="fake",
        prompt_id="extract_invoice",
        prompt_version="v1",
        latency_ms=0,
        input_tokens=None,
        output_tokens=None,
        cached=False,
        cached_at=None,
        raw=raw,
    )
    return normalise(raw, meta, doc)


def with_confidence(ex: InvoiceExtraction, field: str, confidence: float) -> InvoiceExtraction:
    fv = getattr(ex, field).model_copy(update={"confidence": confidence})
    return ex.model_copy(update={field: fv})


def ledger_row(run_id: int, **kw: Any) -> LedgerEntry:
    base: dict[str, Any] = {
        "run_id": run_id,
        "vendor_id": "V001",
        "invoice_number": "SPI/26-27/0187",
        "invoice_number_canonical": "2627187",
        "invoice_date": date(2026, 10, 3),
        "total": "68145.00",
        "po_number": "KF-PO-0126",
        "file_sha256": "a" * 64,
        "final_outcome": "APPROVE",
        "billed_lines": [BilledLine(po_line_no=1, qty=Decimal(1500), amount="57750.00")],
        "display_id": f"R-{run_id:04d}",
    }
    return LedgerEntry.model_validate(base | kw)


def make_ctx(
    extraction: InvoiceExtraction | None = None,
    *,
    vendor: str | None = "V001",
    matched_by: str = "gstin",
    po: str | None = "KF-PO-0142",
    po_method: POMethod = "explicit",
    po_confirmed: bool = False,
    billed: dict[int, str] | None = None,
    received: dict[int, str] | None = None,
    ledger_rows: list[LedgerEntry] | None = None,
    file_rows: list[LedgerEntry] | None = None,
    sender_email: str | None = None,
    overrides: ReviewOverrides | None = None,
    pol: Policy | None = None,
    today: date = TODAY,
    file_sha256: str | None = "b" * 64,
) -> RuleContext:
    w = world()
    ex = extraction or make_extraction()
    v = w.vendors[vendor] if vendor else None
    match = VendorMatch(
        v,
        matched_by if v else "none",  # type: ignore[arg-type]
        1.0 if v else 0.0,
        ex.supplier_gstin.value if isinstance(ex.supplier_gstin.value, str) else None,
        v.legal_name if v else None,
    )
    order = w.purchase_orders[po] if po else None
    balances: dict[int, POLineBalance] = {}
    grns: list[GoodsReceipt] = []
    if order is not None:
        three_way = order.match_type == MatchType.three_way
        for ln in order.lines:
            got = (
                Decimal((received or {}).get(ln.line_no, str(ln.quantity)))
                if three_way
                else Decimal(0)
            )
            done = Decimal((billed or {}).get(ln.line_no, "0"))
            balances[ln.line_no] = POLineBalance(
                po_number=order.po_number,
                line_no=ln.line_no,
                ordered=ln.quantity,
                received=got,
                billed=done,
                remaining_to_bill=ln.quantity - done,
                received_unbilled=(got - done) if three_way else None,
                invoices=[],
            )
            if three_way and got > 0:
                grns.append(
                    GoodsReceipt(
                        grn_number=f"GRN-T{ln.line_no}",
                        po_number=order.po_number,
                        line_no=ln.line_no,
                        quantity_received=got,
                        received_date=date(2026, 11, 10),
                    )
                )
    return RuleContext(
        extraction=ex,
        company=w.company,
        policy=pol or policy(),
        today=today,
        vendor_match=match,
        po=order,
        po_method=po_method,
        po_confirmed=po_confirmed,
        balances=balances,
        grns=grns,
        ledger_rows=ledger_rows or [],
        file_rows=file_rows or [],
        sender_email=sender_email,
        overrides=overrides or ReviewOverrides(),
        file_sha256=file_sha256,
    )


def non_pass(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if r.status.value in ("warn", "fail")]


def codes(results: list[CheckResult]) -> list[str]:
    return [r.code.value for r in non_pass(results) if r.code is not None]


def statuses(results: list[CheckResult]) -> list[str]:
    return [r.status.value for r in results]
