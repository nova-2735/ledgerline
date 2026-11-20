from __future__ import annotations

from decimal import Decimal

import pytest

from app.demo.money import amount_in_words
from app.extract.words2num import words_to_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # S01 as printed by the generator, and the CONTRACTS §10 example
        ("Rupees One Lakh Sixteen Thousand Three Hundred and Forty-Eight Only", "116348.00"),
        ("Rupees One Lakh Sixteen Thousand Three Hundred Forty Eight Only", "116348.00"),
        # S07 (western digits, Indian words)
        ("Rupees Four Lakh Seventy-Two Thousand Only", "472000.00"),
        ("Rupees Seven Lakh Thirty-One Thousand Six Hundred Only", "731600.00"),
        ("Rupees One Lakh Only", "100000.00"),
        ("Rupees Twelve Crore Fifty Lakh Only", "125000000.00"),
        ("Rupees Ten and Fifty Paise Only", "10.50"),
        ("INR One Hundred and Five and Five Paise Only", "105.05"),
        ("Indian Rupees Forty-Three Thousand Three Hundred and Six Only", "43306.00"),
    ],
)
def test_words_to_amount(text: str, expected: str) -> None:
    assert words_to_amount(text) == Decimal(expected)


@pytest.mark.parametrize(
    "text", [None, "", "Only", "Rupees banana Only", "Ten and Two Hundred Paise"]
)
def test_words_to_amount_rejects(text: str | None) -> None:
    assert words_to_amount(text) is None


@pytest.mark.parametrize(
    "value", ["116348", "472000", "43306", "68145", "731600", "99.99", "1000001"]
)
def test_round_trip_with_generator(value: str) -> None:
    assert words_to_amount(amount_in_words(Decimal(value))) == Decimal(value)
