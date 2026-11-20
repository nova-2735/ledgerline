from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.decide.explain import explain, polish_accepted
from app.decide.handoff import Facts
from app.enums import CheckStatus, Outcome, ReasonCode, Route, Severity, StageName
from app.llm.base import LLMClient, LLMUnavailableError
from app.models.checks import CheckResult
from tests.rules.builders import make_ctx

TEMPLATE = (
    "Hold for the buyer: Sharma Packaging Industries invoice SPI/26-27/0214 for ₹1,16,348.00. "
    "Pay 30 boxes now (₹51,330.00 incl. GST). 17 of 19 checks passed."
)


def test_guard_rejects_dropped_number() -> None:
    dropped = "Hold for the buyer: Sharma's invoice for ₹1,16,348.00 needs a look. 17 of 19 passed."
    assert not polish_accepted(TEMPLATE, dropped, Outcome.HOLD)


def test_guard_accepts_rewrite_with_all_numbers() -> None:
    kept = (
        "We're holding SPI/26-27/0214 from Sharma Packaging Industries (₹1,16,348.00) for the "
        "buyer: 30 boxes can be paid now (₹51,330.00 incl. GST); 17 of 19 checks passed."
    )
    assert polish_accepted(TEMPLATE, kept, Outcome.HOLD)


def test_guard_needs_outcome_word_and_a_change() -> None:
    no_word = TEMPLATE.replace("Hold for", "Waiting on")
    assert not polish_accepted(TEMPLATE, no_word, Outcome.HOLD)
    assert not polish_accepted(TEMPLATE, TEMPLATE, Outcome.HOLD)


class StubClient(LLMClient):
    provider = "stub"
    model = "stub-model"
    model_light = "stub-light"
    is_live = True

    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply

    def extract_invoice(self, pdf_bytes: bytes, doc: Any) -> Any:
        raise NotImplementedError

    def map_lines(self, inv: Any, po: Any) -> Any:
        return []

    def polish(self, summary: str, facts: dict[str, Any]) -> str:
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply.replace("{summary}", summary)


def _primary() -> CheckResult:
    return CheckResult(
        rule_id="M04_po_remaining",
        stage=StageName.match_lines,
        status=CheckStatus.fail,
        code=ReasonCode.QTY_EXCEEDS_PO_REMAINING,
        severity=Severity.high,
        title="More than the PO has left",
        message="Pay 30 boxes now (₹51,330.00 incl. GST).",
        evidence={},
        route=Route.buyer,
        outcome_hint=Outcome.HOLD,
        amount_at_risk=Decimal("17110.00"),
    )


def _explain(client: LLMClient | None, polish: bool = True):  # type: ignore[no-untyped-def]
    ctx = make_ctx()
    facts = Facts.build(ctx.extraction, ctx, Decimal("500000.00"))
    primary = _primary()
    return explain(Outcome.HOLD, Route.buyer, primary, [primary], facts, vendor_message=None,
                   internal_note=None, client=client, polish=polish)  # fmt: skip


def test_explain_falls_back_to_template() -> None:
    template = _explain(None)
    assert template.generated_by == "template" and "₹51,330.00" in template.summary
    dropped = _explain(StubClient("Hold: please check this invoice."))
    assert dropped.generated_by == "template" and dropped.summary == template.summary
    broken = _explain(StubClient(LLMUnavailableError("down")))
    assert broken.generated_by == "template"
    off = _explain(StubClient("Hold — {summary}"), polish=False)
    assert off.generated_by == "template"


def test_explain_accepts_safe_polish() -> None:
    polished = _explain(StubClient("On hold — {summary}"))
    assert polished.generated_by == "llm" and polished.model == "stub-light"
    assert polished.summary.startswith("On hold — ")
    assert polished.bullets == ["Pay 30 boxes now (₹51,330.00 incl. GST)."]
