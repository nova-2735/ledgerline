from __future__ import annotations

import pytest

from app.enums import CheckStatus, Outcome, Route, Severity
from app.rules import vendor as v
from app.rules.base import Resolution, ReviewOverrides
from tests.rules.builders import codes, make_ctx, make_extraction, statuses


def test_v01_branches() -> None:
    assert codes(v.v01_resolve(make_ctx())) == []
    [warn] = v.v01_resolve(make_ctx(matched_by="name"))
    assert warn.code == "VENDOR_MATCHED_BY_NAME" and warn.status == CheckStatus.warn
    [fail] = v.v01_resolve(make_ctx(vendor=None))
    assert fail.code == "VENDOR_NOT_FOUND" and fail.route == Route.procurement
    assert fail.outcome_hint == Outcome.HOLD and str(fail.amount_at_risk) == "116348.00"


def test_v02_blocked_vendor() -> None:
    [res] = v.v02_status(make_ctx(vendor="V009"))
    assert res.code == "VENDOR_BLOCKED" and res.outcome_hint == Outcome.REJECT
    assert "Failed food-safety audit" in res.message
    assert statuses(v.v02_status(make_ctx())) == ["pass"]
    assert statuses(v.v02_status(make_ctx(vendor=None))) == ["skip"]


@pytest.mark.parametrize(
    ("matched_by", "gstin", "expected"),
    [
        ("gstin", "27AAKFS2231P1ZS", []),
        ("name", "27AAKFS2231P1ZS", []),
        ("name", "29ABHPO1234D1ZW", ["VENDOR_GSTIN_MISMATCH"]),
        ("name", None, []),
    ],
)
def test_v03_gstin_consistency(matched_by: str, gstin: str | None, expected: list[str]) -> None:
    ctx = make_ctx(make_extraction(supplier_gstin=gstin), matched_by=matched_by)
    assert codes(v.v03_gstin_consistency(ctx)) == expected


@pytest.mark.parametrize(
    ("account", "ifsc", "expected"),
    [
        ("50200012345678", "HDFC0000123", []),
        ("5020 0012 3456 78", "hdfc0000123", []),
        (None, None, []),
        ("012345678901", "YESB0000123", ["BANK_DETAILS_CHANGED"]),
        ("50200012345678", "HDFC0000999", ["BANK_DETAILS_CHANGED"]),
        (None, "YESB0000123", ["BANK_DETAILS_CHANGED"]),
    ],
)
def test_v04_bank_details(account: str | None, ifsc: str | None, expected: list[str]) -> None:
    ex = make_extraction(bank_account_number=account, bank_ifsc=ifsc)
    assert codes(v.v04_bank_details(make_ctx(ex))) == expected


def test_v04_evidence_and_review() -> None:
    ex = make_extraction(
        bank_account_number="012345678901",
        bank_ifsc="YESB0000123",
        bank_name="YES Bank",
        annotations=["Please note our bank details have changed."],
    )
    [res] = v.v04_bank_details(make_ctx(ex))
    assert res.severity == Severity.critical and res.route == Route.treasury
    assert res.evidence["on_file"]["account"] == "****5678"
    assert res.evidence["invoice"]["account"] == "****8901"
    assert res.evidence["notice"] == ["Please note our bank details have changed."]
    assert "+91 20 2712 4455" in res.message
    overrides = ReviewOverrides(
        bank_verified=True,
        resolutions={"bank_verified": Resolution(reviewer="Treasury", note="Called vendor")},
    )
    [done] = v.v04_bank_details(make_ctx(ex, overrides=overrides))
    assert done.resolved_by_review and done.message.endswith("Resolved by Treasury: Called vendor")


@pytest.mark.parametrize(
    ("vendor_id", "sender", "expected"),
    [
        ("V001", None, "skip"),
        ("V001", "accounts@sharmapackaging.example", "pass"),
        ("V001", "billing@SharmaPackaging.example", "pass"),  # same domain
        ("V001", "accounts@sharma-packaging.example", "warn"),
        ("V004", "raoandsons.electricals@mail.example", "pass"),  # free mail: full address
        ("V004", "someone.else@mail.example", "warn"),
        ("V001", "sharma.packaging@gmail.com", "warn"),
    ],
)
def test_v05_sender(vendor_id: str, sender: str | None, expected: str) -> None:
    results = v.v05_sender(make_ctx(vendor=vendor_id, sender_email=sender))
    assert statuses(results) == [expected]
    if expected == "warn":
        assert codes(results) == ["SENDER_DOMAIN_MISMATCH"]
