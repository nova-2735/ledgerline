from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.extract.normalize import (
    AMBIGUOUS_NOTE,
    bank_account_valid,
    canonical_invoice_number,
    canonical_po,
    currency_code,
    ifsc_valid,
    invoice_number_valid,
    mask_account,
    normalize_account,
    normalize_gstin,
    parse_amount,
    parse_amount_noted,
    parse_date,
    parse_quantity,
    parse_rate,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,16,348.00", "116348.00"),
        ("116,348.00", "116348.00"),
        ("Rs. 43,306/-", "43306.00"),
        ("(500.00)", "-500.00"),
        ("₹ 7,627.12", "7627.12"),
        ("₹1,16,348.00", "116348.00"),
        ("INR 472,000.00", "472000.00"),
        ("Rs 1,00,000", "100000.00"),
        ("1,16,348/-", "116348.00"),
        ("+0.40", "0.40"),
        ("-0.20", "-0.20"),
        ("500.00-", "-500.00"),
        ("38.5", "38.50"),
    ],
)
def test_parse_amount(text: str, expected: str) -> None:
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", [None, "", "abc", "1.2.3", "Rs.", "12,34a"])
def test_parse_amount_rejects(text: str | None) -> None:
    assert parse_amount(text) is None


def test_parse_amount_notes_cr_dr() -> None:
    value, notes = parse_amount_noted("5,000.00 Cr")
    assert value == Decimal("5000.00") and notes == ["Cr suffix"]


@pytest.mark.parametrize(
    ("text", "qty", "unit"),
    [
        ("2,000 Nos", "2000", "Nos"),
        ("10 Coil", "10", "Coil"),
        ("1", "1", None),
        ("2.5 Kg", "2.5", "Kg"),
    ],
)
def test_parse_quantity(text: str, qty: str, unit: str | None) -> None:
    assert parse_quantity(text) == (Decimal(qty), unit)


@pytest.mark.parametrize("text", ["18%", "18.0 %", "@18", "18"])
def test_parse_rate(text: str) -> None:
    assert parse_rate(text) == Decimal("18")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12/11/2026", date(2026, 11, 12)),  # V001
        ("14-11-2026", date(2026, 11, 14)),  # V002
        ("15.11.2026", date(2026, 11, 15)),  # V003
        ("18/11/2026", date(2026, 11, 18)),  # V004
        ("05 Nov 2026", date(2026, 11, 5)),  # V005
        ("01-Nov-2026", date(2026, 11, 1)),  # V006
        ("16/11/2026", date(2026, 11, 16)),  # V007
        ("17-11-2026", date(2026, 11, 17)),  # V008
        ("16/11/26", date(2026, 11, 16)),  # Om Sai
        ("14.11.2026", date(2026, 11, 14)),  # V009
        ("03-Oct-2026", date(2026, 10, 3)),
        ("2026-11-20", date(2026, 11, 20)),
        ("Nov 5, 2026", date(2026, 11, 5)),
        ("5 November 2026", date(2026, 11, 5)),
        ("19 Sept 2026", date(2026, 9, 19)),
    ],
)
def test_parse_date_styles(text: str, expected: date) -> None:
    parsed = parse_date(text)
    assert parsed is not None and parsed.value == expected


def test_parse_date_ambiguous_note() -> None:
    parsed = parse_date("03/04/2026")
    assert parsed is not None
    assert parsed.value == date(2026, 4, 3)
    assert parsed.notes == [AMBIGUOUS_NOTE]
    clear = parse_date("16/11/2026")
    assert clear is not None and clear.notes == []
    same = parse_date("05/05/2026")
    assert same is not None and same.notes == []


@pytest.mark.parametrize("text", ["31/02/2026", "next tuesday", "2026/13/01", None])
def test_parse_date_rejects(text: str | None) -> None:
    assert parse_date(text) is None


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("SPI/26-27/0187", "2627187"),
        ("SPI-2627-187", "2627187"),
        ("SPI/26-27/0214", "2627214"),
        ("NCS/INV/2026/0932", "2026932"),
        ("RSE/0457", "457"),
        ("ABC", "ABC"),
    ],
)
def test_canonical_invoice_number(text: str, canonical: str) -> None:
    assert canonical_invoice_number(text) == canonical


@pytest.mark.parametrize(
    "text", ["KF-PO-0142", "KFPO142", "PO#: 0142", "KF PO 0142", "KFPO/0142", "0142", "142"]
)
def test_canonical_po(text: str) -> None:
    assert canonical_po(text) == "142"


def test_canonical_po_blanket_suffix() -> None:
    assert canonical_po("KF-PO-0119 (Blanket)") == "119"


def test_gstin_valid_and_cleaned() -> None:
    res = normalize_gstin(" 29aajck4417m1z1 ")
    assert res is not None and res.valid and res.value == "29AAJCK4417M1Z1" and res.notes == []
    res = normalize_gstin("29-AAJCK-4417M1Z1")
    assert res is not None and res.valid


@pytest.mark.parametrize(
    ("ocr", "fixed", "pos"),
    [
        ("29AAJCK44I7M1Z1", "29AAJCK4417M1Z1", 10),  # I read for 1 in the digit block
        ("2BAAJCK4417M1Z1", "29AAJCK4417M1Z1", None),  # B→8 doesn't validate: no repair
        ("27AAKFS2231P1Z5", "27AAKFS2231P1ZS", 15),  # 5 read for S in the check character
    ],
)
def test_gstin_ocr_repair(ocr: str, fixed: str, pos: int | None) -> None:
    res = normalize_gstin(ocr)
    assert res is not None
    if pos is None:
        assert not res.valid and res.notes == []
    else:
        assert res.valid and res.value == fixed
        assert res.notes == [f"OCR repair at position {pos}"]


def test_gstin_invalid_without_single_repair() -> None:
    res = normalize_gstin("29AAJCK4417M1Z9")
    assert res is not None and not res.valid


def test_bank_and_ifsc() -> None:
    assert normalize_account("A/c 5020 0012 345678") == "50200012345678"
    assert bank_account_valid("50200012345678")
    assert not bank_account_valid("12345")
    assert mask_account("50200012345678") == "****5678"
    assert ifsc_valid("HDFC0000123") and not ifsc_valid("HDFC1000123")


def test_invoice_number_format_and_currency() -> None:
    assert invoice_number_valid("SPI/26-27/0214")
    assert invoice_number_valid("NCS/INV/2026/0932")  # 17 chars, as Nimbus prints them
    assert not invoice_number_valid("THIS-IS-A-VERY-LONG-NUMBER")
    assert not invoice_number_valid("SPI 26 27")
    assert currency_code("Rs.") == currency_code("₹") == currency_code("INR") == "INR"
    assert currency_code(None) == "INR"
