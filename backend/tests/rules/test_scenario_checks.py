"""Every inbox scenario (and two history items) against SCENARIOS §5–§6 expectations.

The extraction is the fake provider's transcription of the generated PDF, normalised and grounded
by the real extractor; reference data and the approved history come from `helpers/world`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.enums import CheckStatus, StageName
from app.models.checks import CheckResult
from app.rules import matching
from app.rules.base import Resolution, ReviewOverrides
from app.rules.registry import all_rules
from tests.helpers.world import SeededWorld, expectations, run_checks

pytestmark = pytest.mark.scenarios

DECIDE_ONLY = {"APPROVAL_LIMIT_EXCEEDED"}  # added by the decision step, not by the rules
INBOX = [f"S{i:02d}" for i in range(1, 16)]


def run_doc(
    world: SeededWorld, doc_id: str, overrides: ReviewOverrides | None = None
) -> tuple[list[CheckResult], Any]:
    return run_checks(world, doc_id, overrides)


def active_codes(results: list[CheckResult]) -> set[str]:
    return {
        r.code.value
        for r in results
        if r.code is not None
        and r.status in (CheckStatus.warn, CheckStatus.fail)
        and not r.resolved_by_review
    }


@pytest.mark.parametrize("doc_id", INBOX)
def test_inbox_codes_match_expectations(seeded_world: SeededWorld, doc_id: str) -> None:
    exp = expectations()[doc_id]
    required = set(exp["required"]) - DECIDE_ONLY
    allowed = set(exp["required"]) | set(exp.get("allowed", []))
    results, _ = run_doc(seeded_world, doc_id)
    got = active_codes(results)
    assert required <= got, f"{doc_id}: missing {sorted(required - got)}"
    assert got <= allowed, f"{doc_id}: unexpected {sorted(got - allowed)}"
    assert {r.rule_id for r in results} == {r.rule_id for r in all_rules()}


def test_s01_everything_passes(seeded_world: SeededWorld) -> None:
    results, ctx = run_doc(seeded_world, "S01")
    assert active_codes(results) == set()
    assert ctx.po_method == "explicit" and ctx.po.po_number == "KF-PO-0142"


def test_s03_amounts_at_risk(seeded_world: SeededWorld) -> None:
    results, _ = run_doc(seeded_world, "S03")
    risk = {r.code.value: r.amount_at_risk for r in results if r.code}
    assert risk["QTY_EXCEEDS_PO_REMAINING"] == Decimal("17110.00")
    assert risk["QTY_EXCEEDS_RECEIVED"] == Decimal("34220.00")


def test_s04_inferred_then_confirmed(seeded_world: SeededWorld) -> None:
    results, ctx = run_doc(seeded_world, "S04")
    assert ctx.po_method == "inferred" and ctx.po.po_number == "KF-PO-0151"
    matched = [r for r in results if r.stage == StageName.match_lines]
    assert all(r.status == CheckStatus.pass_ for r in matched)
    assert all("Against inferred PO KF-PO-0151" in r.message for r in matched)

    review = ReviewOverrides(
        po_number="KF-PO-0151",
        fields_verified=True,
        resolutions={
            "po_number": Resolution(reviewer="Priya Nair (AP)", note="Matches GRN-0951"),
            "fields_verified": Resolution(reviewer="Priya Nair (AP)", note="Checked the scan"),
        },
    )
    after, ctx2 = run_doc(seeded_world, "S04", review)
    assert ctx2.po_confirmed
    assert active_codes(after) == set()
    assert any(r.code and r.code.value == "PO_INFERRED" and r.resolved_by_review for r in after)


def test_s05_points_at_h03(seeded_world: SeededWorld) -> None:
    results, _ = run_doc(seeded_world, "S05")
    [dup] = [r for r in results if r.code and r.code.value == "DUPLICATE_SAME_INVOICE"]
    assert dup.evidence["run_id"] == seeded_world.run_ids["H03"]
    assert dup.evidence["original_invoice_number"] == "SPI/26-27/0187"
    assert dup.amount_at_risk == Decimal("68145.00")


def test_s06_bank_change_then_verified(seeded_world: SeededWorld) -> None:
    results, _ = run_doc(seeded_world, "S06")
    [bank] = [r for r in results if r.code and r.code.value == "BANK_DETAILS_CHANGED"]
    assert bank.evidence["invoice"]["account"] == "****8901"
    assert bank.amount_at_risk == Decimal("52510.00")
    review = ReviewOverrides(
        bank_verified=True,
        resolutions={
            "bank_verified": Resolution(reviewer="Treasury", note="Called +91 79 2658 3300")
        },
    )
    after, _ = run_doc(seeded_world, "S06", review)
    fails = [r for r in after if r.status == CheckStatus.fail and not r.resolved_by_review]
    assert fails == []


def test_s07_view_splits_bundle(seeded_world: SeededWorld) -> None:
    _, ctx = run_doc(seeded_world, "S07")
    [row] = matching.build_view(ctx).rows
    assert row.kind == "bundled" and row.po_line_nos == [1, 2]


def test_s11_skips_matching(seeded_world: SeededWorld) -> None:
    results, ctx = run_doc(seeded_world, "S11")
    assert ctx.vendor is None and ctx.po.po_number == "KF-PO-0142"
    matched = [r for r in results if r.stage == StageName.match_lines]
    assert {r.status for r in matched} == {CheckStatus.skip}
    assert "different vendor" in matched[0].message


def test_s12_numbers(seeded_world: SeededWorld) -> None:
    results, _ = run_doc(seeded_world, "S12")
    [price] = [r for r in results if r.code and r.code.value == "PRICE_VARIANCE_OVER_TOL"]
    assert price.evidence["delta_pct"] == "8.52" and price.amount_at_risk == Decimal("3681.60")


@pytest.mark.parametrize("doc_id", ["H19", "H23"])
def test_history_not_in_ledger(seeded_world: SeededWorld, doc_id: str) -> None:
    exp = expectations()[doc_id]
    got = active_codes(run_doc(seeded_world, doc_id)[0])
    assert set(exp["required"]) <= got
    assert got <= set(exp["required"]) | set(exp.get("allowed", []))
