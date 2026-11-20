"""Rules + decision for every inbox scenario against scenarios.yaml (outcome and route)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.decide.decision import evaluate, redecide
from app.decide.policy import load_policy
from app.enums import Outcome, ReasonCode
from app.models.decision import Decision
from app.rules.base import Resolution, ReviewOverrides, RuleContext
from tests.helpers.world import SeededWorld, expectations, run_checks

pytestmark = pytest.mark.scenarios
INBOX = [f"S{i:02d}" for i in range(1, 16)]


def decide_doc(
    world: SeededWorld, doc_id: str, overrides: ReviewOverrides | None = None, version: int = 1
) -> tuple[Decision, RuleContext]:
    checks, ctx = run_checks(world, doc_id, overrides)
    result = evaluate(checks, ctx.extraction, ctx.policy, version, ctx=ctx, polish=False)
    return result.decision, ctx


@pytest.mark.parametrize("doc_id", INBOX)
def test_outcome_and_route(seeded_world: SeededWorld, doc_id: str) -> None:
    exp = expectations()[doc_id]
    d, _ = decide_doc(seeded_world, doc_id)
    assert (d.outcome.value, d.route.value) == (exp["outcome"], exp["route"]), d.reasons
    required = [ReasonCode(c) for c in exp["required"]]
    assert set(required) <= set(d.reasons)
    if d.outcome != Outcome.APPROVE:
        assert d.primary_reason == (required[0] if required else d.primary_reason)
        assert d.handoff is not None and d.handoff.question
    assert d.final is (d.outcome in (Outcome.APPROVE, Outcome.REJECT))
    assert (d.posting is not None) is (d.outcome == Outcome.APPROVE)


def test_s01_posting(seeded_world: SeededWorld) -> None:
    d, _ = decide_doc(seeded_world, "S01")
    assert d.reasons == [] and d.posting is not None
    assert {ln.gl_account for ln in d.posting.lines} == {"510200"}
    assert d.posting.due_date == date(2026, 12, 12)
    assert d.headline.startswith("Approve for payment — ")


def test_s02_notes(seeded_world: SeededWorld) -> None:
    d, _ = decide_doc(seeded_world, "S02")
    assert d.reasons == [ReasonCode.PRICE_VARIANCE_WITHIN_TOL, ReasonCode.ROUND_OFF_APPLIED]
    assert len(d.notes) == 2 and d.headline.endswith("with notes")


def test_s03_partial_payment_suggestion(seeded_world: SeededWorld) -> None:
    d, _ = decide_doc(seeded_world, "S03")
    assert d.handoff is not None
    assert "₹51,330.00" in d.handoff.suggested_action
    assert "credit note for 20" in d.handoff.suggested_action
    assert d.handoff.amount_at_risk == Decimal("34220.00")
    assert d.explanation.vendor_message is not None
    assert d.explanation.vendor_message.to == "ar@apexindustrial.example"


def test_s04_confirm_po_approves(seeded_world: SeededWorld) -> None:
    d, _ = decide_doc(seeded_world, "S04")
    assert d.handoff is not None and "KF-PO-0151" in d.handoff.question
    review = ReviewOverrides(
        po_number="KF-PO-0151",
        fields_verified=True,
        resolutions={"po_number": Resolution(reviewer="Priya Nair (AP)", note="Matches GRN-0951")},
    )
    after, _ = decide_doc(seeded_world, "S04", review, version=2)
    assert (after.outcome, after.version) == (Outcome.APPROVE, 2)
    assert after.posting is not None and after.posting.lines[0].po_number == "KF-PO-0151"


def test_s06_bank_change(seeded_world: SeededWorld) -> None:
    d, _ = decide_doc(seeded_world, "S06")
    assert d.primary_reason == ReasonCode.BANK_DETAILS_CHANGED
    assert d.explanation.vendor_message is None
    note = d.explanation.internal_note
    assert note is not None and note.to == "Treasury" and "+91 79 2658 3300" in note.body
    review = ReviewOverrides(
        bank_verified=True,
        resolutions={"bank_verified": Resolution(reviewer="Treasury", note="Called on file no.")},
    )
    after, _ = decide_doc(seeded_world, "S06", review, version=2)
    assert after.outcome == Outcome.APPROVE
    assert after.posting is not None and after.posting.remit_to["bank_name"] == "HDFC Bank"


def test_s09_draft_asks_for_cgst_sgst(seeded_world: SeededWorld) -> None:
    d, _ = decide_doc(seeded_world, "S09")
    msg = d.explanation.vendor_message
    assert msg is not None and msg.to == "sales@bharatoffice.example"
    assert "CGST 9% ₹3,690.00 + SGST 9% ₹3,690.00" in msg.body


def test_s11_question_mentions_quoted_po(seeded_world: SeededWorld) -> None:
    d, _ = decide_doc(seeded_world, "S11")
    assert d.handoff is not None
    assert (
        "it quotes KF-PO-0142, which belongs to Sharma Packaging Industries" in d.handoff.question
    )
    assert d.explanation.vendor_message is None  # unknown vendor: no master address


def test_s14_draft_asks_for_tax_invoice_and_po_amendment(seeded_world: SeededWorld) -> None:
    d, _ = decide_doc(seeded_world, "S14")
    msg = d.explanation.vendor_message
    assert msg is not None and "tax invoice" in msg.body and "amend the PO" in msg.body


def test_s12_policy_what_if(seeded_world: SeededWorld) -> None:
    exp = expectations()["S12"]["what_if"]
    _, ctx = decide_doc(seeded_world, "S12")
    relaxed = load_policy().with_overrides({k: v for k, v in exp.items() if k != "outcome"})
    result = redecide(ctx, relaxed, polish=False)
    assert result.decision.outcome.value == exp["outcome"]
    assert result.decision.policy_version == relaxed.policy_version
    assert ctx.policy == load_policy()  # the stored context is untouched
