"""Purchase-order checks (RULES §1.4, stage `resolve_po`)."""

from __future__ import annotations

from typing import Any

from app.enums import Outcome, ReasonCode, Route, Severity, StageName
from app.models.checks import CheckResult
from app.rules.base import Emitter, RuleContext, rule, text_value

STAGE = StageName.resolve_po


def _candidates(ctx: RuleContext) -> list[dict[str, Any]]:
    return [c.model_dump() for c in ctx.po_candidates]


def _top_line(ctx: RuleContext) -> str:
    if not ctx.po_candidates:
        return ""
    top = ctx.po_candidates[0]
    return f"{top.po_number} (a {round(top.score * 100)}% match: {top.reason})"


def _confirmed(ctx: RuleContext, result: CheckResult) -> CheckResult:
    return ctx.resolve(result, "po_number") if ctx.po_confirmed else result


def vendor_mismatch(ctx: RuleContext) -> bool:
    """The resolved PO belongs to another vendor, or the vendor is unknown (P03)."""
    if ctx.po is None:
        return False
    return ctx.vendor is None or ctx.po.vendor_id != ctx.vendor.vendor_id


@rule("P01_explicit", STAGE)
def p01_explicit(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    printed = text_value(ctx.extraction.po_reference)
    if printed is None:
        return [e.skip("PO number on the invoice", "No PO number printed; see PO inference.")]
    evidence: dict[str, Any] = {
        "printed": printed,
        "canonical": ctx.extraction.po_reference_canonical,
        "method": ctx.po_method,
        "candidates": _candidates(ctx),
    }
    if ctx.po_method == "explicit" and ctx.po is not None:
        return [
            e.passed(
                "PO found",
                f'Printed reference "{printed}" is {ctx.po.po_number}.',
                evidence | {"po_number": ctx.po.po_number},
            )
        ]
    if ctx.po_method == "inferred_ref_miss" and ctx.po_candidates:
        top = ctx.po_candidates[0]
        result = e.fail(
            ReasonCode.PO_INFERRED,
            "PO inferred (printed reference not found)",
            f'The printed PO reference "{printed}" doesn\'t match any PO; the closest open PO is '
            f"{_top_line(ctx)}. The buyer should confirm it.",
            severity=Severity.high,
            route=Route.buyer,
            hint=Outcome.HOLD,
            evidence=evidence | {"po_number": top.po_number, "note": "printed ref not found"},
        )
        return [_confirmed(ctx, result)]
    result = e.fail(
        ReasonCode.PO_NOT_FOUND,
        "PO not found",
        f'The printed PO reference "{printed}" doesn\'t match any PO, and no open PO of this '
        "vendor fits the invoice clearly. The buyer should say which PO this bills.",
        severity=Severity.high,
        route=Route.buyer,
        hint=Outcome.HOLD,
        evidence=evidence,
    )
    return [_confirmed(ctx, result)]


@rule("P02_inference", STAGE)
def p02_inference(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    if text_value(ctx.extraction.po_reference) is not None:
        return [e.skip("PO inference", "A PO number is printed; inference not needed.")]
    pol = ctx.policy.po_inference
    evidence: dict[str, Any] = {
        "method": ctx.po_method,
        "candidates": _candidates(ctx),
        "min_score": pol.min_score,
        "min_margin": pol.min_margin,
    }
    if ctx.po_method == "inferred" and ctx.po_candidates:
        top = ctx.po_candidates[0]
        evidence["po_number"] = top.po_number
        if pol.auto_accept_inferred:
            return [
                e.passed(
                    "PO inferred and accepted",
                    f"No PO printed; matched {_top_line(ctx)}.",
                    evidence,
                )
            ]
        result = e.fail(
            ReasonCode.PO_INFERRED,
            "PO inferred, needs confirmation",
            f"No PO number printed. The best match is {_top_line(ctx)}. "
            "An AP clerk should confirm it before the lines are matched.",
            severity=Severity.medium,
            route=Route.ap_clerk,
            hint=Outcome.HOLD,
            evidence=evidence,
        )
        return [_confirmed(ctx, result)]
    if ctx.po_method == "ambiguous":
        close = [c.po_number for c in ctx.po_candidates if c.score >= pol.min_score]
        result = e.fail(
            ReasonCode.PO_AMBIGUOUS,
            "More than one PO fits",
            f"No PO number printed and {len(close)} open POs fit about equally well "
            f"({', '.join(close)}). Pick the right one.",
            severity=Severity.medium,
            route=Route.ap_clerk,
            hint=Outcome.HOLD,
            evidence=evidence,
        )
        return [_confirmed(ctx, result)]
    # Name the closest PO only when its items at least partly match; a PO that shares nothing
    # but the vendor is noise for the reader.
    closest = ctx.po_candidates[0] if ctx.po_candidates else None
    best = (
        f" The closest was {_top_line(ctx)}."
        if closest and closest.components.get("lines", 0) >= 0.6
        else ""
    )
    result = e.fail(
        ReasonCode.PO_MISSING,
        "No PO for this invoice",
        f"No PO number printed and no open PO of this vendor fits the invoice.{best} "
        "The buyer should raise or name a PO.",
        severity=Severity.high,
        route=Route.buyer,
        hint=Outcome.HOLD,
        evidence=evidence,
    )
    return [_confirmed(ctx, result)]


@rule("P03_vendor", STAGE)
def p03_vendor(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    po = ctx.po
    if po is None:
        return [e.skip("PO belongs to vendor", "No PO resolved.")]
    evidence = {"po_number": po.po_number, "po_vendor_id": po.vendor_id,
                "invoice_vendor_id": ctx.vendor.vendor_id if ctx.vendor else None}  # fmt: skip
    if not vendor_mismatch(ctx):
        return [
            e.passed("PO belongs to vendor", f"{po.po_number} was raised on this vendor.", evidence)
        ]
    who = ctx.vendor.legal_name if ctx.vendor else "a supplier who is not in the vendor master"
    return [
        e.fail(
            ReasonCode.PO_VENDOR_MISMATCH,
            "PO belongs to a different vendor",
            f"{po.po_number} was raised on vendor {po.vendor_id}, but this invoice is from {who}.",
            severity=Severity.high,
            route=Route.buyer,
            hint=Outcome.HOLD,
            evidence=evidence,
        )
    ]


@rule("P04_status", STAGE)
def p04_status(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    po = ctx.po
    if po is None:
        return [e.skip("PO is open", "No PO resolved.")]
    if po.status != "open":
        return [
            e.fail(
                ReasonCode.PO_CLOSED,
                f"PO is {po.status}",
                f"{po.po_number} is {po.status}; it can't take new invoices without the buyer.",
                severity=Severity.medium,
                route=Route.buyer,
                hint=Outcome.HOLD,
                evidence={"po_number": po.po_number, "status": po.status},
            )
        ]
    return [e.passed("PO is open", f"{po.po_number} is open.")]


@rule("P05_currency_date", STAGE)
def p05_currency_date(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    po = ctx.po
    currency = ctx.extraction.currency
    if po is None:
        if currency != "INR":
            return [
                e.fail(
                    ReasonCode.CURRENCY_MISMATCH,
                    f"Invoice is in {currency}, not INR",
                    f"The invoice is billed in {currency}. Payments and POs are in INR, so "
                    "finance has to agree the exchange rate and any reverse-charge GST before "
                    "it can be booked.",
                    severity=Severity.medium,
                    route=Route.ap_clerk,
                    hint=Outcome.HOLD,
                    evidence={"expected": "INR", "actual": currency},
                )
            ]
        return [e.skip("Currency and PO date", "No PO resolved.")]
    out = []
    if currency != po.currency:
        out.append(
            e.fail(
                ReasonCode.CURRENCY_MISMATCH,
                "Currency differs from PO",
                f"The invoice is in {currency} but {po.po_number} is in {po.currency}.",
                severity=Severity.medium,
                route=Route.buyer,
                hint=Outcome.HOLD,
                evidence={"expected": po.currency, "actual": currency},
            )
        )
    else:
        out.append(e.passed("Currency matches PO", f"Both in {currency}."))
    inv_date = ctx.invoice_date
    if inv_date is not None and inv_date < po.po_date:
        out.append(
            e.warn(
                ReasonCode.DATE_BEFORE_PO,
                "Invoice dated before the PO",
                f"The invoice is dated {inv_date:%d %b %Y}, before {po.po_number} was raised "
                f"({po.po_date:%d %b %Y}).",
                severity=Severity.low,
                route=Route.buyer,
                evidence={"invoice_date": inv_date.isoformat(), "po_date": po.po_date.isoformat()},
            )
        )
    elif inv_date is not None:
        out.append(e.passed("Invoice dated after the PO", f"PO raised {po.po_date:%d %b %Y}."))
    return out


RULES = [p01_explicit, p02_inference, p03_vendor, p04_status, p05_currency_date]
