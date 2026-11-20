"""Resolve the invoice's supplier to the vendor master: GSTIN first, then name/alias."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz, utils
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.extraction import InvoiceExtraction
from app.models.reference import Vendor
from app.orm import VendorRow
from app.reference import gstin as gstin_util
from app.reference.loader import vendor_from_row

NAME_THRESHOLD = 90.0


@dataclass(frozen=True)
class VendorMatch:
    vendor: Vendor | None
    matched_by: Literal["gstin", "name", "none"]
    score: float  # 1.0 for a GSTIN match, token_set_ratio/100 for a name match
    invoice_gstin: str | None = None
    matched_name: str | None = None


def _invoice_gstin(extraction: InvoiceExtraction) -> str | None:
    field = extraction.supplier_gstin
    for text in (field.value, field.raw):
        if isinstance(text, str) and text.strip():
            res = gstin_util.repair(text)
            if res is not None:
                return res.value
    return None


def _invoice_name(extraction: InvoiceExtraction) -> str | None:
    field = extraction.supplier_name
    for text in (field.value, field.raw):
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def name_score(a: str, b: str) -> float:
    """token_set_ratio on lowercased, punctuation-free names (0–100)."""
    return fuzz.token_set_ratio(a, b, processor=utils.default_process)


def all_vendors(session: Session) -> list[Vendor]:
    rows = session.scalars(select(VendorRow).order_by(VendorRow.vendor_id))
    return [vendor_from_row(r) for r in rows]


def get_vendor(session: Session, vendor_id: str) -> Vendor | None:
    row = session.get(VendorRow, vendor_id)
    return vendor_from_row(row) if row else None


def resolve_vendor(session: Session, extraction: InvoiceExtraction) -> VendorMatch:
    """GSTIN exact in the master → `gstin`; else best name/alias token_set_ratio ≥ 90 → `name`;
    else `none` (RULES §1.2 V01). Ties on name score go to the lower vendor id."""
    vendors = all_vendors(session)
    inv_gstin = _invoice_gstin(extraction)
    if inv_gstin:
        for v in vendors:
            if gstin_util.clean(v.gstin) == inv_gstin:
                return VendorMatch(v, "gstin", 1.0, inv_gstin, v.legal_name)

    name = _invoice_name(extraction)
    best: tuple[float, Vendor, str] | None = None
    if name:
        for v in vendors:
            for candidate in (v.legal_name, *v.aliases):
                score = name_score(name, candidate)
                if best is None or score > best[0]:
                    best = (score, v, candidate)
    if best is not None and best[0] >= NAME_THRESHOLD:
        return VendorMatch(best[1], "name", round(best[0] / 100, 4), inv_gstin, best[2])
    top = round(best[0] / 100, 4) if best else 0.0
    return VendorMatch(None, "none", top, inv_gstin, None)
