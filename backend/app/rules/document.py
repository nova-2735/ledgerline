"""Document checks (RULES §1.1, stage `validate_document`)."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

from app.enums import DocType, Outcome, ReasonCode, Route, Severity, StageName
from app.extract.extractor import CRITICAL_FIELDS
from app.models.checks import CheckResult
from app.models.extraction import InvoiceExtraction
from app.rules.base import (
    Emitter,
    Rule,
    RuleContext,
    decimal_value,
    inr,
    q2,
    rule,
    text_value,
)

STAGE = StageName.validate_document

FIELD_LABELS = {
    "invoice_number": "invoice number",
    "invoice_date": "invoice date",
    "supplier_gstin": "supplier GSTIN",
    "total": "total",
    "bank_account_number": "bank account number",
}


@rule("D00_legible", STAGE)
def d00_legible(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    ex = ctx.extraction
    if ex.total.value is None and ex.invoice_number.value is None and ex.legibility == "poor":
        return [
            e.fail(
                ReasonCode.DOC_UNREADABLE,
                "Document can't be read",
                "The document is too poor to read: no invoice number and no total could be found. "
                "Ask the vendor for a clearer copy.",
                severity=Severity.high,
                route=Route.vendor,
                hint=Outcome.RETURN,
                evidence={"legibility": ex.legibility},
            )
        ]
    return [e.passed("Document is readable", f"Legibility: {ex.legibility.replace('_', ' ')}.")]


_DOC_NAMES = {
    DocType.purchase_order: "a purchase order",
    DocType.receipt: "a receipt",
    DocType.statement: "a statement of account",
}


# A printed title that asks for payment ("BILL", "Cash Bill", "Bill of Supply", "Invoice") makes
# a document the model filed under "other" payable after all: small and unregistered suppliers
# issue plain bills, not GST tax invoices.
_PAYABLE_TITLE = re.compile(r"\b(invoice|bill)\b", re.IGNORECASE)
_NOT_PAYABLE_TITLE = re.compile(
    r"\b(pro-?forma|e-?way|lading|entry|challan|receipt|statement|quotation|estimate|order)\b",
    re.IGNORECASE,
)


def effective_doc_type(ex: InvoiceExtraction) -> DocType:
    """The model's classification, except that a bill it filed under "other" is treated as an
    invoice when it prints a total and either a bill/invoice title or a bill number (and no
    title such as "Delivery Challan" or "Receipt" says otherwise)."""
    if ex.doc_type == DocType.other and ex.total.value is not None:
        title = ex.meta.raw.document_title or ""
        if _NOT_PAYABLE_TITLE.search(title):
            return ex.doc_type
        if _PAYABLE_TITLE.search(title) or text_value(ex.invoice_number):
            return DocType.tax_invoice
    return ex.doc_type


@rule("D01_doc_type", STAGE)
def d01_doc_type(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    ex = ctx.extraction
    kind = effective_doc_type(ex)
    evidence = {"doc_type": kind.value}
    if kind == DocType.tax_invoice:
        if ex.doc_type != kind:
            title = ex.meta.raw.document_title
            why = (
                f"Titled “{title}”"
                if title
                else f"No heading, but it has bill number {text_value(ex.invoice_number)} "
                f"and a total of {inr(decimal_value(ex.total))}"
            )
            return [
                e.passed(
                    "Bill for payment",
                    f"{why}: a bill asking for payment, so it is checked as an invoice.",
                    evidence | {"model_doc_type": ex.doc_type.value},
                )
            ]
        return [e.passed("Tax invoice", "The document is a tax invoice.", evidence)]
    if kind == DocType.proforma_invoice:
        return [
            e.fail(
                ReasonCode.DOC_PROFORMA,
                "Proforma, not a tax invoice",
                "This is a proforma invoice, which can't be booked or paid. "
                "Ask the vendor for a tax invoice.",
                severity=Severity.high,
                route=Route.vendor,
                hint=Outcome.RETURN,
                evidence=evidence,
            )
        ]
    if kind in (DocType.credit_note, DocType.debit_note):
        label = "credit note" if kind == DocType.credit_note else "debit note"
        return [
            e.fail(
                ReasonCode.DOC_CREDIT_NOTE,
                f"Document is a {label}",
                "This is a credit note: it lowers what we owe the vendor, so it is booked "
                "against their account, not paid."
                if kind == DocType.credit_note
                else "This is a debit note: it adds a charge to an earlier invoice, so it is "
                "checked against that invoice before anything is paid.",
                severity=Severity.high,
                route=Route.ap_clerk,
                hint=Outcome.HOLD,
                evidence=evidence,
            )
        ]
    title = (ex.meta.raw.document_title or "").strip()
    name = _DOC_NAMES.get(kind) or (f"a {title.lower()}" if title else None)
    text = (
        f"This is {name}, not an invoice, so there is nothing to pay."
        if name
        else "This document isn't an invoice, so there is nothing to pay."
    )
    return [
        e.fail(
            ReasonCode.DOC_NOT_INVOICE,
            "Not an invoice",
            text,
            severity=Severity.high,
            route=Route.none,
            hint=Outcome.REJECT,
            evidence=evidence,
        )
    ]


def missing_fields(ctx: RuleContext) -> set[str]:
    """Fields D02 reports as missing (D03 skips these)."""
    ex = ctx.extraction
    out = set()
    if text_value(ex.invoice_number) is None:
        out.add("invoice_number")
    if ex.invoice_date.value is None:
        out.add("invoice_date")
    if ex.total.value is None:
        out.add("total")
    if ex.supplier_name.value is None and ex.supplier_gstin.value is None:
        out.add("supplier")
    return out


_REQUIRED = (
    ("invoice_number", ReasonCode.FIELD_MISSING_INVOICE_NUMBER, "invoice number"),
    ("invoice_date", ReasonCode.FIELD_MISSING_INVOICE_DATE, "invoice date"),
    ("total", ReasonCode.FIELD_MISSING_TOTAL, "invoice total"),
    ("supplier", ReasonCode.FIELD_MISSING_SUPPLIER, "supplier name or GSTIN"),
)


def _article(label: str) -> str:
    return "an" if label[0] in "aeiou" else "a"


@rule("D02_required", STAGE)
def d02_required(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    missing = missing_fields(ctx)
    out = []
    for key, code, label in _REQUIRED:
        if key in missing:
            out.append(
                e.fail(
                    code,
                    f"No {label} printed",
                    f"The invoice doesn't show {_article(label)} {label}. "
                    "Ask the vendor to re-issue it.",
                    severity=Severity.high,
                    route=Route.vendor,
                    hint=Outcome.RETURN,
                    evidence={"field": key},
                )
            )
        else:
            out.append(
                e.passed(
                    f"{label[0].upper()}{label[1:]} present",
                    f"Found the {label}.",
                    {"field": key},
                )
            )
    return out


@rule("D03_confidence", STAGE)
def d03_confidence(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    ex = ctx.extraction
    skip = missing_fields(ctx)
    threshold = ctx.policy.extraction.min_confidence_critical
    low = []
    for name in CRITICAL_FIELDS:
        fv = getattr(ex, name)
        if name in skip or fv.value is None:
            continue
        if fv.confidence < threshold:
            low.append(
                {
                    "field": name,
                    "label": FIELD_LABELS.get(name, name.replace("_", " ")),
                    "confidence": fv.confidence,
                    "raw": fv.raw,
                    "bbox": [b.model_dump() for b in fv.bbox],
                }
            )
    if not low:
        return [
            e.passed(
                "Key fields read clearly",
                "Invoice number, date, GSTIN and total were all read with at least "
                f"{round(threshold * 100)}% confidence.",
            )
        ]
    listed = ", ".join(f"{f['label']} ({round(f['confidence'] * 100)}% sure)" for f in low)
    result = e.fail(
        ReasonCode.FIELD_LOW_CONFIDENCE,
        "Some key fields need a second look",
        f"These couldn't be confirmed on the page: {listed}. Check them against the document "
        "before approving.",
        severity=Severity.medium,
        route=Route.ap_clerk,
        hint=Outcome.HOLD,
        evidence={"fields": low, "threshold": threshold},
    )
    return [ctx.resolve(result, "fields_verified")]


@rule("D04_line_math", STAGE)
def d04_line_math(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    bad = []
    checked = 0
    for ln in ctx.extraction.line_items:
        if ln.quantity is None or ln.unit_price is None or ln.amount is None:
            continue
        checked += 1
        expected = q2(ln.quantity * ln.unit_price)
        tolerance = max(Decimal("1.00"), abs(ln.amount) * Decimal("0.001"))
        if abs(expected - ln.amount) > tolerance:
            bad.append(
                {
                    "line": ln.index + 1,
                    "expected": str(expected),
                    "actual": str(ln.amount),
                    "delta": str(ln.amount - expected),
                }
            )
    if not checked:
        return [e.skip("Line arithmetic", "No line shows quantity, rate and amount together.")]
    if not bad:
        return [e.passed("Line amounts add up", f"Quantity × rate = amount on {checked} lines.")]
    first = bad[0]
    more = f" ({len(bad)} lines affected)." if len(bad) > 1 else "."
    return [
        e.fail(
            ReasonCode.MATH_LINE_MISMATCH,
            "Line amounts don't add up",
            f"Line {first['line']}: quantity × rate is {inr(Decimal(str(first['expected'])))} but "
            f"the invoice shows {inr(Decimal(str(first['actual'])))}{more}",
            severity=Severity.medium,
            route=Route.vendor,
            hint=Outcome.RETURN,
            evidence={"lines": bad},
        )
    ]


def line_sum(ctx: RuleContext, taxable: bool) -> Decimal | None:
    values = [(ln.taxable_amount if taxable else ln.amount) for ln in ctx.extraction.line_items]
    if not values or any(v is None for v in values):
        return None
    return sum((v for v in values if v is not None), Decimal())


@rule("D05_subtotal", STAGE)
def d05_subtotal(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    subtotal = decimal_value(ctx.extraction.subtotal)
    if subtotal is None:
        return [e.skip("Subtotal", "No subtotal printed.")]
    lines = line_sum(ctx, taxable=ctx.extraction.prices_include_tax)
    if lines is None:
        return [
            e.skip("Subtotal", "Some line amounts are missing, so the subtotal can't be checked.")
        ]
    delta = subtotal - lines
    evidence = {"expected": str(lines), "actual": str(subtotal), "delta": str(delta)}
    if abs(delta) > ctx.policy.tolerances.rounding_abs:
        return [
            e.fail(
                ReasonCode.MATH_SUBTOTAL_MISMATCH,
                "Subtotal doesn't match the lines",
                f"The lines add up to {inr(lines)} but the subtotal shows {inr(subtotal)}.",
                severity=Severity.medium,
                route=Route.vendor,
                hint=Outcome.RETURN,
                evidence=evidence,
            )
        ]
    return [e.passed("Subtotal matches the lines", f"Lines add up to {inr(lines)}.", evidence)]


def _expected_total(ctx: RuleContext, round_off: Decimal) -> tuple[Decimal | None, str]:
    ex = ctx.extraction
    if ex.prices_include_tax:
        base = line_sum(ctx, taxable=False)
        if base is None:
            return None, ""
        return base + ex.other_charges_total + round_off, "lines (tax included)"
    sub = decimal_value(ex.subtotal)
    base = sub if sub is not None else line_sum(ctx, taxable=False)
    if base is None:
        return None, ""
    return base + ex.tax.total_tax + ex.other_charges_total + round_off, "subtotal and tax"


@rule("D06_total", STAGE)
def d06_total(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    ex = ctx.extraction
    total = ctx.total
    round_off = decimal_value(ex.round_off) or Decimal("0.00")
    out: list[CheckResult] = []
    expected, how = _expected_total(ctx, round_off)
    if total is None:
        out.append(e.skip("Invoice total", "No total printed."))
    elif expected is None:
        out.append(
            e.skip("Invoice total", "Line amounts are missing, so the total can't be checked.")
        )
    else:
        delta = total - expected
        evidence = {"expected": str(expected), "actual": str(total), "delta": str(delta)}
        if abs(delta) > ctx.policy.tolerances.rounding_abs:
            direction = "more" if delta > 0 else "less"
            out.append(
                e.fail(
                    ReasonCode.MATH_TOTAL_MISMATCH,
                    "Total doesn't add up",
                    f"The {how} come to {inr(expected)} but the invoice total is {inr(total)} "
                    f"({inr(abs(delta))} {direction}).",
                    severity=Severity.medium,
                    route=Route.vendor,
                    hint=Outcome.RETURN,
                    evidence=evidence,
                    at_risk=abs(delta),
                )
            )
        else:
            out.append(e.passed("Total adds up", f"The {how} come to {inr(total)}.", evidence))
    if round_off != 0 and abs(round_off) <= Decimal("1.00"):
        sign = "+" if round_off > 0 else "−"
        out.append(
            e.warn(
                ReasonCode.ROUND_OFF_APPLIED,
                "Rounded to the rupee",
                f"The vendor rounded the total by {sign}{inr(abs(round_off))}.",
                evidence={"round_off": str(round_off)},
            )
        )
    if ex.prices_include_tax:
        taxable = line_sum(ctx, taxable=True)
        out.append(
            e.warn(
                ReasonCode.TAX_INCLUSIVE_NORMALIZED,
                "Prices include GST",
                f"Prices on this invoice include GST; the taxable value works out to "
                f"{inr(taxable)} and GST to {inr(ex.tax.total_tax)}.",
                evidence={"taxable": str(taxable) if taxable is not None else None},
            )
        )
    return out


@rule("D07_words", STAGE)
def d07_words(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    words = decimal_value(ctx.extraction.amount_in_words)
    total = ctx.total
    if words is None or total is None:
        return [e.skip("Amount in words", "No amount in words that could be read.")]
    if words != total:
        return [
            e.warn(
                ReasonCode.TOTAL_WORDS_MISMATCH,
                "Amount in words differs",
                f"The amount in words reads {inr(words)} but the total in figures is {inr(total)}.",
                severity=Severity.low,
                evidence={"words": str(words), "total": str(total)},
            )
        ]
    return [e.passed("Amount in words matches", f"Words and figures both say {inr(total)}.")]


@rule("D08_dates", STAGE)
def d08_dates(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    inv_date = ctx.invoice_date
    if inv_date is None:
        return [e.skip("Invoice date", "No invoice date to check.")]
    evidence = {"invoice_date": inv_date.isoformat(), "today": ctx.today.isoformat()}
    if inv_date > ctx.today:
        return [
            e.fail(
                ReasonCode.DATE_IN_FUTURE,
                "Invoice dated in the future",
                f"The invoice is dated {inv_date:%d %b %Y}, after today ({ctx.today:%d %b %Y}).",
                severity=Severity.high,
                route=Route.vendor,
                hint=Outcome.RETURN,
                evidence=evidence,
            )
        ]
    max_age = ctx.policy.dates.max_age_days
    if inv_date < ctx.today - timedelta(days=max_age):
        age = (ctx.today - inv_date).days
        return [
            e.fail(
                ReasonCode.DATE_STALE,
                "Old invoice",
                f"The invoice is {age} days old (limit {max_age} days).",
                severity=Severity.low,
                route=Route.ap_clerk,
                hint=Outcome.HOLD,
                evidence=evidence | {"age_days": age},
            )
        ]
    return [e.passed("Invoice date is reasonable", f"Dated {inv_date:%d %b %Y}.", evidence)]


@rule("D09_single_invoice", STAGE)
def d09_single_invoice(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    found = ctx.extraction.invoices_in_file
    if len(found) < 2:
        return [e.passed("One invoice in the file", "No second invoice number heads a page.")]
    listed = " and ".join(", ".join(found).rsplit(", ", 1))
    return [
        e.fail(
            ReasonCode.DOC_MULTIPLE_INVOICES,
            f"File contains {len(found)} invoices",
            f"This PDF contains {len(found)} invoices ({listed}), one after another. Each "
            "invoice has to be checked and paid on its own, so this file wasn't checked further.",
            severity=Severity.high,
            route=Route.ap_clerk,
            hint=Outcome.HOLD,
            evidence={"invoices": found},
        )
    ]


def not_an_invoice(ctx: RuleContext) -> bool:
    """D01 reports DOC_NOT_INVOICE: field and arithmetic checks would only add noise."""
    return effective_doc_type(ctx.extraction) not in _INVOICE_LIKE


_INVOICE_LIKE = frozenset(
    {DocType.tax_invoice, DocType.proforma_invoice, DocType.credit_note, DocType.debit_note}
)


def _invoice_only(r: Rule) -> Rule:
    def fn(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
        if not_an_invoice(ctx):
            return [e.skip(r.rule_id, "Skipped: the document is not an invoice.")]
        return r.fn(ctx, e)

    return Rule(r.rule_id, r.stage, fn)


RULES = [
    d00_legible,
    d01_doc_type,
    *(
        _invoice_only(r)
        for r in (
            d02_required,
            d03_confidence,
            d04_line_math,
            d05_subtotal,
            d06_total,
            d07_words,
            d08_dates,
            d09_single_invoice,
        )  # fmt: skip
    ),
]
