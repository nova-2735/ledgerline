from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import db
from app.demo.invoice import load_world
from app.orm import CompanyRow, GoodsReceiptRow, POLineRow, PurchaseOrderRow, VendorRow
from app.reference import gstin
from app.reference.loader import load_reference, read_reference
from app.reference.similarity import description_similarity, normalize_description
from tests.helpers.world import SeededWorld


def _count(session: Session, table: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def test_counts_match_world(seeded_world: SeededWorld) -> None:
    world = load_world()
    expected_lines = sum(len(po.lines) for po in world.purchase_orders.values())
    assert seeded_world.counts == {
        "company": 1,
        "vendors": 9,
        "purchase_orders": 32,
        "po_lines": expected_lines,
        "goods_receipts": len(world.goods_receipts),
    }
    s = seeded_world.session
    assert _count(s, VendorRow) == 9
    assert _count(s, PurchaseOrderRow) == 32
    assert _count(s, POLineRow) == expected_lines
    assert _count(s, GoodsReceiptRow) == len(world.goods_receipts)
    company = s.get(CompanyRow, 1)
    assert company is not None and company.gstin == "29AAJCK4417M1Z1"


def test_load_is_idempotent(seeded_world: SeededWorld) -> None:
    again = load_reference(seeded_world.session, seeded_world.root)
    assert again == seeded_world.counts
    assert _count(seeded_world.session, VendorRow) == 9
    assert _count(seeded_world.session, POLineRow) == seeded_world.counts["po_lines"]


def test_loaded_values_round_trip(seeded_world: SeededWorld) -> None:
    s = seeded_world.session
    v009 = s.get(VendorRow, "V009")
    assert v009 is not None and v009.status == "blocked"
    assert "food-safety" in (v009.block_reason or "")
    v002 = s.get(VendorRow, "V002")
    assert v002 is not None and v002.aliases == ["Deccan Cold Chain", "DCC Logistics"]
    v001 = s.get(VendorRow, "V001")
    assert v001 is not None and v001.block_reason is None
    po = s.get(PurchaseOrderRow, "KF-PO-0133")
    assert po is not None and po.match_type == "two_way"
    assert [str(ln.unit_price) for ln in po.lines] == ["360000.00", "40000.00"]


def test_accepts_reference_folder_and_reports_missing(demo_world: Path, tmp_path: Path) -> None:
    _, vendors, pos, _ = read_reference(demo_world / "reference")
    assert len(vendors) == 9 and len(pos) == 32
    broken = tmp_path / "broken"
    shutil.copytree(demo_world / "reference", broken)
    (broken / "goods_receipts.csv").unlink()
    db.init_db()
    with db.get_sessionmaker()() as session, pytest.raises(FileNotFoundError):
        load_reference(session, broken)


@pytest.mark.parametrize(
    ("value", "valid", "state", "pan"),
    [
        ("27AAKFS2231P1ZS", True, "27", "AAKFS2231P"),
        ("29aadcd7781k1z1", True, "29", "AADCD7781K"),
        ("29 AAJCK 4417 M1Z1", True, "29", "AAJCK4417M"),
        ("27AAKFS2231P1ZT", False, "27", "AAKFS2231P"),
        ("", False, "", ""),
    ],
)
def test_gstin_helpers(value: str, valid: bool, state: str, pan: str) -> None:
    assert gstin.validate(value) is valid
    assert gstin.state_code(value) == state
    assert gstin.pan(value) == pan


def test_gstin_ocr_repair() -> None:
    fixed = gstin.repair("27AAKFS223IP1ZS")  # "I" read for "1" at a digit position
    assert fixed is not None and fixed.valid and fixed.value == "27AAKFS2231P1ZS"
    assert fixed.notes == ["OCR repair at position 11"]
    assert gstin.repair(None) is None
    bad = gstin.repair("NOT-A-GSTIN")
    assert bad is not None and not bad.valid


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("MCB 32A double pole", "mcb 32 a double pole"),
        ("Copper wire 2.5mm FRLS 90 mtr", "copper wire 2.5 mm frls 90 m"),
        ("FRLS copper cable 2.5 sq mm, 90 m coil", "frls copper cable 2.5 sqmm 90 m coil"),
        ("Cable 4 mm2", "cable 4 sqmm"),
        ("MCB 32 Amp DP", "mcb 32 a dp"),
        ("Box of 100 nos, with lid", "box 100 nos lid"),
    ],
)
def test_normalize_description(text: str, expected: str) -> None:
    assert normalize_description(text) == expected


def test_description_similarity_orders_sensibly() -> None:
    cable = "FRLS copper cable 2.5 sq mm, 90 m coil"
    assert description_similarity("Copper wire 2.5mm FRLS 90 mtr", cable) > 0.75
    assert description_similarity("LED panel light 40W, 2x2 ft", cable) < 0.5
    assert description_similarity(None, cable) == 0.0
