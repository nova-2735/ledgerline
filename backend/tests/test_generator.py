from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from stdnum.in_ import gstin as gstin_mod

from app.config import get_settings
from app.demo import generate as gen
from app.demo.invoice import load_specs, load_world
from app.demo.money import amount_in_words, format_indian, format_western, round_off
from app.models.extraction import RawInvoice

COMPANY_GSTIN = "29AAJCK4417M1Z1"
SCANNED = {"S04", "S05", "H13"}

# id: (subtotal, total tax, round-off, total) — numbers from SCENARIOS §5–§6
EXPECTED_TOTALS: dict[str, tuple[str, str, str, str]] = {
    "S01": ("98600.00", "17748.00", "0.00", "116348.00"),
    "S02": ("102870.00", "18516.60", "0.40", "121387.00"),
    "S03": ("72500.00", "13050.00", "0.00", "85550.00"),
    "S04": ("36700.00", "6606.00", "0.00", "43306.00"),
    "S05": ("57750.00", "10395.00", "0.00", "68145.00"),
    "S06": ("44500.00", "8010.00", "0.00", "52510.00"),
    "S07": ("400000.00", "72000.00", "0.00", "472000.00"),
    "S08": ("84745.76", "15254.24", "0.00", "100000.00"),
    "S09": ("41000.00", "7380.00", "0.00", "48380.00"),
    "S10": ("38000.00", "6840.00", "0.00", "44840.00"),
    "S11": ("25600.00", "4608.00", "0.00", "30208.00"),
    "S12": ("39720.00", "7149.60", "0.40", "46870.00"),
    "S13": ("620000.00", "111600.00", "0.00", "731600.00"),
    "S14": ("144000.00", "25920.00", "0.00", "169920.00"),
    "S15": ("45000.00", "2250.00", "0.00", "47250.00"),
    "H01": ("58000.00", "10440.00", "0.00", "68440.00"),
    "H02": ("29000.00", "5220.00", "0.00", "34220.00"),
    "H03": ("57750.00", "10395.00", "0.00", "68145.00"),
    "H04": ("38500.00", "6930.00", "0.00", "45430.00"),
    "H05": ("85000.00", "15300.00", "0.00", "100300.00"),
    "H06": ("84745.76", "15254.24", "0.00", "100000.00"),
    "H07": ("19600.00", "3528.00", "0.00", "23128.00"),
    "H08": ("45000.00", "8100.00", "0.00", "53100.00"),
    "H09": ("36540.00", "6577.20", "-0.20", "43117.00"),
    "H10": ("68000.00", "12240.00", "0.00", "80240.00"),
    "H11": ("20988.00", "3777.84", "0.16", "24766.00"),
    "H12": ("84745.76", "15254.24", "0.00", "100000.00"),
    "H13": ("17550.00", "3159.00", "0.00", "20709.00"),
    "H14": ("30800.00", "5544.00", "0.00", "36344.00"),
    "H15": ("51000.00", "9180.00", "0.00", "60180.00"),
    "H16": ("51000.00", "9180.00", "0.00", "60180.00"),
    "H17": ("14700.00", "2646.00", "0.00", "17346.00"),
    "H18": ("16000.00", "2880.00", "0.00", "18880.00"),
    "H19": ("30800.00", "5544.00", "0.00", "36344.00"),
    "H20": ("18000.00", "3240.00", "0.00", "21240.00"),
    "H21": ("450000.00", "81000.00", "0.00", "531000.00"),
    "H22": ("12500.00", "2250.00", "0.00", "14750.00"),
    "H23": ("13200.00", "2376.00", "0.00", "15576.00"),
    "H24": ("42500.00", "7650.00", "0.00", "50150.00"),
}


def _hashes(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def world_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("demo")
    gen.generate(out)
    return out


@pytest.fixture(scope="module")
def truth(world_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (world_dir / "truth").glob("[SH]*.json")
    }


def _text(path: Path) -> str:
    with pymupdf.open(path) as doc:
        return " ".join(page.get_text() for page in doc)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# --- money ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "indian", "western"),
    [
        ("116348", "1,16,348.00", "116,348.00"),
        ("100000", "1,00,000.00", "100,000.00"),
        ("731600", "7,31,600.00", "731,600.00"),
        ("12345678.5", "1,23,45,678.50", "12,345,678.50"),
        ("999", "999.00", "999.00"),
        ("-0.20", "-0.20", "-0.20"),
    ],
)
def test_amount_formats(value: str, indian: str, western: str) -> None:
    assert format_indian(Decimal(value)) == indian
    assert format_western(Decimal(value)) == western


def test_amount_in_words() -> None:
    assert (
        amount_in_words(Decimal("116348"))
        == "Rupees One Lakh Sixteen Thousand Three Hundred and Forty-Eight Only"
    )
    assert amount_in_words(Decimal("472000")) == "Rupees Four Lakh Seventy-Two Thousand Only"
    assert amount_in_words(Decimal("10.50")) == "Rupees Ten and Fifty Paise Only"


@pytest.mark.parametrize(
    ("amount", "total", "delta"),
    [
        ("121386.60", "121387.00", "0.40"),
        ("43117.20", "43117.00", "-0.20"),
        ("100.50", "101.00", "0.50"),
    ],
)
def test_round_off(amount: str, total: str, delta: str) -> None:
    assert round_off(Decimal(amount)) == (Decimal(total), Decimal(delta))


# --- world ---------------------------------------------------------------------------------------


def test_world_references_are_consistent() -> None:
    world = load_world()
    specs = load_specs(world)
    for po in world.purchase_orders.values():
        assert po.vendor_id in world.vendors
    for grn in world.goods_receipts:
        po = world.purchase_orders[grn.po_number]
        assert any(ln.line_no == grn.line_no for ln in po.lines)
    for spec in specs:
        if spec.po_number:
            assert spec.po_number in world.purchase_orders, spec.id
    received = sum(g.quantity_received for g in world.goods_receipts if g.po_number == "KF-PO-0119")
    assert received == 90


def test_reference_files(world_dir: Path) -> None:
    ref = world_dir / "reference"
    vendors = (ref / "vendors.csv").read_text(encoding="utf-8").splitlines()
    assert vendors[0].startswith("vendor_id,legal_name,aliases,gstin,pan")
    assert len(vendors) == 10
    pos = (ref / "purchase_orders.csv").read_text(encoding="utf-8").splitlines()
    assert pos[0].startswith("po_number,vendor_id,po_date,status,currency,match_type")
    assert any(line.startswith("KF-PO-0142,V001,2026-10-28,open,INR,three_way") for line in pos)
    company = json.loads((ref / "company.json").read_text(encoding="utf-8"))
    assert company["gstin"] == COMPANY_GSTIN


# --- documents -----------------------------------------------------------------------------------


def test_document_counts_and_pages(world_dir: Path) -> None:
    inbox = sorted((world_dir / "inbox").glob("*.pdf"))
    history = sorted((world_dir / "history").glob("*.pdf"))
    assert [p.stem for p in inbox] == [f"S{i:02d}" for i in range(1, 16)]
    assert [p.stem for p in history] == [f"H{i:02d}" for i in range(1, 25)]
    for path in inbox + history:
        with pymupdf.open(path) as doc:
            assert doc.page_count == 1, path.name


def test_digital_text_layer_has_number_and_total(
    world_dir: Path, truth: dict[str, dict[str, Any]]
) -> None:
    for doc_id, t in truth.items():
        if doc_id in SCANNED or doc_id == "H19":
            continue
        folder = "inbox" if doc_id.startswith("S") else "history"
        text = _flat(_text(world_dir / folder / f"{doc_id}.pdf"))
        raw = t["raw"]
        if raw["invoice_number"]:
            assert raw["invoice_number"] in text, doc_id
        assert raw["total"] in text, doc_id
        assert COMPANY_GSTIN in text, doc_id


def test_scanned_docs_have_no_text_layer(world_dir: Path) -> None:
    for doc_id in SCANNED:
        folder = "inbox" if doc_id.startswith("S") else "history"
        assert len(_text(world_dir / folder / f"{doc_id}.pdf").strip()) < 30, doc_id


def test_gstins_valid_and_company_on_every_invoice(truth: dict[str, dict[str, Any]]) -> None:
    for doc_id, t in truth.items():
        raw = RawInvoice.model_validate(t["raw"])
        assert raw.buyer_gstin == COMPANY_GSTIN, doc_id
        assert raw.supplier_gstin and gstin_mod.is_valid(raw.supplier_gstin), doc_id
    assert gstin_mod.is_valid(COMPANY_GSTIN)


def test_expected_totals(truth: dict[str, dict[str, Any]]) -> None:
    assert set(truth) == set(EXPECTED_TOTALS)
    for doc_id, (subtotal, tax, ro, total) in EXPECTED_TOTALS.items():
        ev = truth[doc_id]["expected_values"]
        assert (ev["subtotal"], ev["total_tax"], ev["round_off"], ev["total"]) == (
            subtotal,
            tax,
            ro,
            total,
        ), doc_id


def test_printed_details(truth: dict[str, dict[str, Any]]) -> None:
    s01 = truth["S01"]["raw"]
    assert s01["invoice_date"] == "12/11/2026"
    assert s01["po_reference"] == "KF-PO-0142"
    assert s01["total"].endswith("1,16,348.00")
    assert s01["tax_lines"] == [{"tax_type": "IGST", "rate": "18%", "amount": "17,748.00"}]
    s02 = truth["S02"]
    assert [t["amount"] for t in s02["raw"]["tax_lines"]] == ["9,258.30", "9,258.30"]
    assert s02["raw"]["round_off"] == "+0.40"
    assert truth["S04"]["raw"]["total"] == "Rs. 43,306/-"
    assert truth["S11"]["raw"]["total"] == "Rs. 30,208/-"
    assert truth["S07"]["raw"]["total"] == "INR 472,000.00"
    s08 = truth["S08"]
    assert s08["raw"]["prices_include_tax"] is True
    assert s08["raw"]["subtotal"] is None
    assert s08["expected_values"]["lines"][0]["taxable_amount"] == "84745.76"
    assert [t["amount"] for t in s08["raw"]["tax_lines"]] == ["7,627.12", "7,627.12"]
    assert [t["tax_type"] for t in truth["S09"]["raw"]["tax_lines"]] == ["IGST"]
    assert truth["S14"]["raw"]["document_type"] == "proforma_invoice"
    s06 = truth["S06"]["raw"]
    assert (s06["bank_name"], s06["bank_account_number"], s06["bank_ifsc"]) == (
        "YES Bank",
        "012345678901",
        "YESB0000123",
    )
    assert s06["supplier_email"] == "accounts@vertexlab-instruments.example"
    assert any("bank details have changed" in a for a in s06["annotations"])
    assert "SECOND REMINDER — PAYMENT OVERDUE" in truth["S05"]["raw"]["annotations"]


def test_not_printed_fields_are_absent(world_dir: Path, truth: dict[str, dict[str, Any]]) -> None:
    for doc_id in ("S10", "H15"):
        assert truth[doc_id]["raw"]["invoice_number"] is None
        folder = "inbox" if doc_id.startswith("S") else "history"
        assert "Invoice No" not in _text(world_dir / folder / f"{doc_id}.pdf"), doc_id
    for doc_id in ("S04", "S15"):
        assert truth[doc_id]["raw"]["po_reference"] is None
    assert "KF-PO" not in _text(world_dir / "inbox" / "S15.pdf")
    assert truth["S01"]["raw"]["due_date"] is None


def test_duplicate_file_and_index(world_dir: Path) -> None:
    manifest = json.loads((world_dir / "manifest.json").read_text(encoding="utf-8"))
    docs = manifest["documents"]
    assert docs["H19"]["sha256"] == docs["H14"]["sha256"]
    assert (world_dir / "history" / "H19.pdf").read_bytes() == (
        world_dir / "history" / "H14.pdf"
    ).read_bytes()
    index = json.loads((world_dir / "truth" / "index.json").read_text(encoding="utf-8"))
    assert index[docs["S01"]["sha256"]] == "S01"
    assert index[docs["H14"]["sha256"]] == "H14"
    assert docs["S04"]["edge_case"] == "E2"
    assert docs["S06"]["email"]["sender_email"] == "accounts@vertexlab-instruments.example"
    assert manifest["history_order"][:3] == ["H04", "H05", "H06"]
    h11 = docs["H11"]
    assert h11["processed_at"].startswith("2026-10-01T")
    assert h11["review"]["at"].startswith("2026-10-02T")
    assert docs["H23"]["awaiting_review"] is True


def test_generation_is_byte_deterministic(world_dir: Path, tmp_path: Path) -> None:
    gen.generate(tmp_path / "again")
    assert _hashes(world_dir) == _hashes(tmp_path / "again")


def _rupee_font() -> Path | None:
    from app.demo.templates.base import _has_rupee

    for candidate in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if candidate.is_file() and _has_rupee(candidate):
            return candidate
    return None


def test_rupee_sign_printed_when_font_has_glyph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    font = _rupee_font()
    if font is None:
        pytest.skip("no font with the ₹ glyph on this machine")
    monkeypatch.setenv("INVOICE_FONT_PATH", str(font))
    get_settings.cache_clear()
    world = load_world()
    spec = next(s for s in load_specs(world) if s.id == "S01")
    pdf, truth = gen.render_document(spec, world, rupee_ok=True)
    path = tmp_path / "S01.pdf"
    path.write_bytes(pdf)
    assert truth["raw"]["total"] == "₹ 1,16,348.00"
    assert "₹ 1,16,348.00" in _flat(_text(path))
