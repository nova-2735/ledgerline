"""GST checks (RULES §1.3, stage `check_tax`)."""

from __future__ import annotations

from decimal import Decimal

from app.enums import Outcome, ReasonCode, Route, Severity, StageName
from app.models.checks import CheckResult
from app.reference import gstin as gstin_util
from app.rules.base import Emitter, RuleContext, inr, q2, rule, text_value

STAGE = StageName.check_tax


def supplier_gstin(ctx: RuleContext) -> str | None:
    value = text_value(ctx.extraction.supplier_gstin)
    return gstin_util.clean(value) if value else None


def gstin_usable(ctx: RuleContext) -> bool:
    return gstin_util.validate(supplier_gstin(ctx))


def gst_charged(ctx: RuleContext) -> bool:
    """Any CGST, SGST or IGST on the invoice (TCS and cess don't count)."""
    tax = ctx.extraction.tax
    return any(v != 0 for v in (tax.cgst, tax.sgst, tax.igst))


@rule("T01_supplier_gstin", STAGE)
def t01_supplier_gstin(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    ex = ctx.extraction
    value = supplier_gstin(ctx)
    if value is None:
        if ex.supplier_name.value is None:
            return [e.skip("Supplier GSTIN", "No supplier details printed (reported above).")]
        if not gst_charged(ctx):
            return [
                e.skip(
                    "Supplier GSTIN",
                    "No GSTIN and no GST charged: the supplier isn't GST-registered in India "
                    "(a small or foreign supplier), so there is no input tax credit to claim.",
                )
            ]
        message = (
            "The invoice charges GST but doesn't show the supplier's GSTIN, so that GST can't "
            "be claimed."
        )
    elif gstin_util.validate(value):
        return [e.passed("Supplier GSTIN is valid", f"GSTIN {value} passes the checksum.")]
    else:
        message = f"Supplier GSTIN {value} is not a valid GSTIN (format or checksum fails)."
    return [
        e.fail(
            ReasonCode.GSTIN_INVALID,
            "Supplier GSTIN is invalid",
            message + " Ask the vendor to correct it.",
            severity=Severity.high,
            route=Route.vendor,
            hint=Outcome.RETURN,
            evidence={"actual": value},
        )
    ]


@rule("T02_buyer_gstin", STAGE)
def t02_buyer_gstin(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    printed = text_value(ctx.extraction.buyer_gstin)
    ours = gstin_util.clean(ctx.company.gstin)
    actual = gstin_util.clean(printed) if printed else None
    evidence = {"expected": ours, "actual": actual}
    if actual == ours:
        return [e.passed("Billed to our GSTIN", f"Buyer GSTIN {ours} is ours.", evidence)]
    if not gst_charged(ctx):
        return [
            e.skip(
                "Billed to our GSTIN",
                "No GST charged, so our GSTIN isn't needed on this bill for input tax credit.",
                evidence,
            )
        ]
    what = f"shows buyer GSTIN {actual}" if actual else "doesn't show our GSTIN"
    return [
        e.fail(
            ReasonCode.BUYER_GSTIN_MISMATCH,
            "Not billed to our GSTIN",
            f"The invoice {what}; it must be billed to {ctx.company.name} ({ours}) "
            "for us to claim input tax credit.",
            severity=Severity.high,
            route=Route.vendor,
            hint=Outcome.RETURN,
            evidence=evidence,
        )
    ]


def _taxable_by_rate(ctx: RuleContext) -> dict[Decimal, Decimal] | None:
    out: dict[Decimal, Decimal] = {}
    for ln in ctx.extraction.line_items:
        if ln.taxable_amount is None or ln.tax_rate_pct is None:
            return None
        out[ln.tax_rate_pct] = out.get(ln.tax_rate_pct, Decimal()) + ln.taxable_amount
    return out or None


@rule("T03_tax_type", STAGE)
def t03_tax_type(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    if not gstin_usable(ctx):
        return [e.skip("Type of GST", "Supplier GSTIN missing or invalid.")]
    tax = ctx.extraction.tax
    if tax.cgst == 0 and tax.sgst == 0 and tax.igst == 0:
        return [e.skip("Type of GST", "No GST charged on this invoice.")]
    supplier_state = gstin_util.state_code(supplier_gstin(ctx) or "")
    buyer_state = ctx.company.state_code
    intra = supplier_state == buyer_state
    evidence: dict[str, object] = {
        "supplier_state": supplier_state,
        "place_of_supply_state": buyer_state,
        "expected": "CGST+SGST" if intra else "IGST",
        "charged": {"cgst": str(tax.cgst), "sgst": str(tax.sgst), "igst": str(tax.igst)},
    }
    if intra:
        ok = tax.igst == 0 and tax.cgst != 0 and tax.sgst != 0
    else:
        ok = tax.cgst == 0 and tax.sgst == 0
    if intra and tax.igst == 0 and not ok:
        missing, present = ("SGST", "CGST") if tax.sgst == 0 else ("CGST", "SGST")
        return [
            e.fail(
                ReasonCode.TAX_TYPE_MISMATCH,
                "Wrong type of GST",
                f"Only {present} was charged. Supplier and buyer are both in "
                f"{gstin_util.state_name(buyer_state)}, "
                f"so the invoice must show both CGST and SGST; without {missing} the tax "
                "can't be claimed in full as input tax credit. Ask the vendor for a corrected "
                "invoice.",
                severity=Severity.high,
                route=Route.vendor,
                hint=Outcome.RETURN,
                evidence=evidence | {"missing": missing},
            )
        ]
    if ok:
        kind = "CGST + SGST" if intra else "IGST"
        where = "within the same state" if intra else "between states"
        return [e.passed("Right type of GST", f"{kind} for a supply {where}.", evidence)]
    if intra:
        rates = _taxable_by_rate(ctx) or {}
        parts = []
        expected_split: dict[str, str] = {}
        for rate, taxable in sorted(rates.items()):
            half = q2(taxable * rate / 2 / 100)
            parts.append(f"CGST {rate / 2:g}% {inr(half)} + SGST {rate / 2:g}% {inr(half)}")
            expected_split[str(rate)] = str(half)
        should = "; ".join(parts) or "CGST + SGST"
        message = (
            f"IGST {inr(tax.igst)} was charged, but supplier and buyer are both in "
            f"{gstin_util.state_name(buyer_state)}, so it should be {should}. IGST charged on a "
            "supply within the state "
            "can't be claimed as input tax credit. Ask the vendor for a corrected invoice."
        )
        evidence["expected_cgst_sgst_each"] = expected_split
    else:
        message = (
            "CGST/SGST was charged, but the supplier is in "
            f"{gstin_util.state_name(supplier_state)} and the buyer in "
            f"{gstin_util.state_name(buyer_state)}, so it should be IGST. "
            "This tax can't be claimed as input tax credit. Ask the vendor for a corrected invoice."
        )
    return [
        e.fail(
            ReasonCode.TAX_TYPE_MISMATCH,
            "Wrong type of GST",
            message,
            severity=Severity.high,
            route=Route.vendor,
            hint=Outcome.RETURN,
            evidence=evidence,
        )
    ]


@rule("T04_tax_amount", STAGE)
def t04_tax_amount(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    if not gstin_usable(ctx):
        return [e.skip("GST amounts", "Supplier GSTIN missing or invalid.")]
    rates = _taxable_by_rate(ctx)
    if rates is None:
        return [e.skip("GST amounts", "Line tax rates or taxable values are missing.")]
    tax = ctx.extraction.tax
    full = sum((taxable * rate / 100 for rate, taxable in rates.items()), Decimal())
    stated = {"CGST": tax.cgst, "SGST": tax.sgst, "IGST": tax.igst}
    expected = {"CGST": q2(full / 2), "SGST": q2(full / 2), "IGST": q2(full)}
    charged = [k for k, v in stated.items() if v != 0]
    if not charged:
        return [e.skip("GST amounts", "No GST charged on this invoice.")]
    # CGST and SGST come as a pair: when either is charged, check both (a missing half is 0).
    if "CGST" in charged or "SGST" in charged:
        charged = [k for k in stated if k in ("CGST", "SGST") or k in charged]
    tolerance = ctx.policy.tolerances.rounding_abs
    out = []
    for kind in charged:
        delta = stated[kind] - expected[kind]
        evidence = {
            "tax_type": kind,
            "expected": str(expected[kind]),
            "actual": str(stated[kind]),
            "delta": str(delta),
        }
        if abs(delta) > tolerance:
            out.append(
                e.fail(
                    ReasonCode.TAX_AMOUNT_MISMATCH,
                    f"{kind} amount is wrong",
                    f"{kind} should be {inr(expected[kind])} on the taxable value, but the "
                    f"invoice charges {inr(stated[kind])} ({inr(abs(delta))} "
                    f"{'too much' if delta > 0 else 'too little'}).",
                    severity=Severity.medium,
                    route=Route.vendor,
                    hint=Outcome.RETURN,
                    evidence=evidence,
                    at_risk=abs(delta),
                )
            )
        else:
            out.append(
                e.passed(f"{kind} amount is right", f"{kind} {inr(stated[kind])}.", evidence)
            )
    return out


RULES = [t01_supplier_gstin, t02_buyer_gstin, t03_tax_type, t04_tax_amount]
