from __future__ import annotations

import pytest

from app.models.extraction import InvoiceExtraction
from app.reference.vendors import resolve_vendor
from tests.helpers.world import SeededWorld


def _with(
    ex: InvoiceExtraction,
    *,
    gstin: str | None = None,
    name: str | None = None,
    drop_gstin: bool = False,
) -> InvoiceExtraction:
    g = ex.supplier_gstin
    if drop_gstin:
        g = g.model_copy(update={"value": None, "raw": None})
    elif gstin is not None:
        g = g.model_copy(update={"value": gstin, "raw": gstin})
    n = ex.supplier_name
    if name is not None:
        n = n.model_copy(update={"value": name, "raw": name})
    return ex.model_copy(update={"supplier_gstin": g, "supplier_name": n})


def test_s01_by_gstin(seeded_world: SeededWorld) -> None:
    m = resolve_vendor(seeded_world.session, seeded_world.extraction("S01"))
    assert m.matched_by == "gstin" and m.vendor is not None
    assert m.vendor.vendor_id == "V001" and m.score == 1.0


@pytest.mark.parametrize("printed", ["27 AAKFS 2231 P1ZS", "27aakfs2231p1zs", "27-AAKFS-2231P1ZS"])
def test_gstin_with_spaces_or_lowercase(seeded_world: SeededWorld, printed: str) -> None:
    ex = _with(seeded_world.extraction("S01"), gstin=printed, name="Someone Else Entirely")
    m = resolve_vendor(seeded_world.session, ex)
    assert m.matched_by == "gstin" and m.vendor and m.vendor.vendor_id == "V001"


def test_gstin_with_one_ocr_slip(seeded_world: SeededWorld) -> None:
    ex = _with(seeded_world.extraction("S01"), gstin="27AAKFS223IP1ZS")
    m = resolve_vendor(seeded_world.session, ex)
    assert m.matched_by == "gstin" and m.vendor and m.vendor.vendor_id == "V001"


def test_name_only_alias(seeded_world: SeededWorld) -> None:
    ex = _with(seeded_world.extraction("S02"), name="Deccan Cold Chain", drop_gstin=True)
    m = resolve_vendor(seeded_world.session, ex)
    assert m.matched_by == "name" and m.vendor and m.vendor.vendor_id == "V002"
    assert m.score >= 0.9


def test_legal_name_with_punctuation(seeded_world: SeededWorld) -> None:
    ex = _with(
        seeded_world.extraction("S08"), name="GREENLEAF FACILITY SERVICES, LLP", drop_gstin=True
    )
    m = resolve_vendor(seeded_world.session, ex)
    assert m.matched_by == "name" and m.vendor and m.vendor.vendor_id == "V006"


def test_om_sai_is_not_found(seeded_world: SeededWorld) -> None:
    m = resolve_vendor(seeded_world.session, seeded_world.extraction("S11"))
    assert m.matched_by == "none" and m.vendor is None
    assert m.invoice_gstin == "29ABHPO1234D1ZW"
    assert m.score < 0.9


def test_blocked_vendor_still_resolves(seeded_world: SeededWorld) -> None:
    m = resolve_vendor(seeded_world.session, seeded_world.extraction("S15"))
    assert m.vendor and m.vendor.vendor_id == "V009" and m.vendor.status == "blocked"


@pytest.mark.parametrize(
    ("doc_id", "vendor_id"),
    [
        ("S01", "V001"),
        ("S02", "V002"),
        ("S03", "V003"),
        ("S04", "V004"),
        ("S07", "V005"),
        ("S08", "V006"),
        ("S06", "V007"),
        ("S09", "V008"),
        ("S15", "V009"),
    ],
)
def test_inbox_invoices_resolve_to_their_vendor(
    seeded_world: SeededWorld, doc_id: str, vendor_id: str
) -> None:
    m = resolve_vendor(seeded_world.session, seeded_world.extraction(doc_id))
    assert m.matched_by == "gstin"
    assert m.vendor and m.vendor.vendor_id == vendor_id
