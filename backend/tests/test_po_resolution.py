from __future__ import annotations

import pytest

from app.extract.normalize import canonical_po
from app.reference.ledger import Ledger
from app.reference.purchase_orders import find_by_reference, infer_candidates
from tests.helpers.world import SeededWorld


@pytest.mark.parametrize(
    ("printed", "vendor_id", "po_number"),
    [
        ("KF-PO-0142", "V001", "KF-PO-0142"),
        ("KFPO/0137", "V002", "KF-PO-0137"),
        ("PO#: 0148", "V008", "KF-PO-0148"),
        ("KF PO 0146", "V007", "KF-PO-0146"),
        ("KF-PO-0119 (Blanket)", "V003", "KF-PO-0119"),
        ("P.O. 110", "V004", "KF-PO-0110"),
    ],
)
def test_reference_variants_resolve(
    seeded_world: SeededWorld, printed: str, vendor_id: str, po_number: str
) -> None:
    hit = find_by_reference(seeded_world.session, canonical_po(printed), vendor_id)
    assert hit is not None and hit.po.po_number == po_number
    assert not hit.vendor_mismatch


def test_wrong_vendor_detected(seeded_world: SeededWorld) -> None:
    hit = find_by_reference(seeded_world.session, canonical_po("PO: KF-PO-0142"), "V004")
    assert hit is not None and hit.po.po_number == "KF-PO-0142"
    assert hit.vendor_mismatch and hit.po.vendor_id == "V001"
    unknown = find_by_reference(seeded_world.session, "142", None)
    assert unknown is not None and unknown.vendor_mismatch


def test_s11_printed_reference_belongs_to_sharma(seeded_world: SeededWorld) -> None:
    ex = seeded_world.extraction("S11")
    hit = find_by_reference(seeded_world.session, ex.po_reference_canonical, None)
    assert hit is not None and hit.po.vendor_id == "V001" and hit.vendor_mismatch


def test_unknown_reference(seeded_world: SeededWorld) -> None:
    assert find_by_reference(seeded_world.session, "9999", "V001") is None
    assert find_by_reference(seeded_world.session, None, "V001") is None


def test_s04_inference_picks_0151(seeded_world: SeededWorld) -> None:
    ex = seeded_world.extraction("S04")
    assert ex.po_reference_canonical is None
    ledger = Ledger(seeded_world.session)
    cands = infer_candidates(seeded_world.session, ex, "V004", ledger)
    by_po = {c.po_number: c for c in cands}
    assert set(by_po) == {"KF-PO-0110", "KF-PO-0128", "KF-PO-0151"}

    top, second = cands[0], cands[1]
    assert top.po_number == "KF-PO-0151"
    assert top.score >= 0.75
    assert top.score - second.score >= 0.15
    assert by_po["KF-PO-0110"].score < 0.60
    assert by_po["KF-PO-0128"].score < 0.60
    assert by_po["KF-PO-0110"].components["amount"] == 0.0  # fully billed by H13
    assert {k: top.components[k] for k in ("amount", "receipt", "date")} == {
        "amount": 1.0,
        "receipt": 1.0,
        "date": 1.0,
    }

    assert "items and prices match 2/2 lines" in top.reason
    assert "amount fits remaining ₹36,700.00" in top.reason
    assert "fully received" in top.reason
    assert "amount exceeds remaining ₹0.00" in by_po["KF-PO-0110"].reason


def test_inference_with_unknown_vendor_is_capped(seeded_world: SeededWorld) -> None:
    cands = infer_candidates(seeded_world.session, seeded_world.extraction("S04"), None)
    assert len(cands) == 20
    assert cands[0].po_number == "KF-PO-0151"


def test_two_way_inference_mentions_no_receipt(seeded_world: SeededWorld) -> None:
    cands = infer_candidates(seeded_world.session, seeded_world.extraction("S02"), "V002")
    assert cands[0].po_number == "KF-PO-0137"
    assert "two-way" in cands[0].reason
    assert cands[0].components["receipt"] == 1.0
