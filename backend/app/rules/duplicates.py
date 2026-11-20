"""Duplicate checks (RULES §1.6, stage `check_duplicates`).

Compared against `invoice_ledger` rows whose final outcome is not REJECT or RETURN, within the
policy window, excluding this run (the context already holds exactly those rows).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz

from app.enums import Outcome, ReasonCode, Route, Severity, StageName
from app.models.checks import CheckResult
from app.reference.ledger import LedgerEntry
from app.rules.base import Emitter, RuleContext, inr, rule, text_value

STAGE = StageName.check_duplicates
_PAST = {
    Outcome.APPROVE: "approved",
    Outcome.HOLD: "held",
    Outcome.REJECT: "rejected",
    Outcome.RETURN: "returned",
}


def _describe(row: LedgerEntry) -> dict[str, Any]:
    return {
        "run_id": row.run_id,
        "display_id": row.display_id,
        "original_invoice_number": row.invoice_number,
        "original_outcome": row.final_outcome.value if row.final_outcome else None,
        "original_date": row.invoice_date.isoformat() if row.invoice_date else None,
        "original_total": str(row.total) if row.total is not None else None,
        "processed_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def _when(row: LedgerEntry) -> str:
    outcome = _PAST.get(row.final_outcome, "processed") if row.final_outcome else "processed"
    when = f" on {row.finished_at:%d %b %Y}" if row.finished_at else ""
    ref = f" ({row.display_id})" if row.display_id else ""
    return f"{outcome}{when}{ref}"


def _x02_matches(ctx: RuleContext) -> list[LedgerEntry]:
    canonical = ctx.extraction.invoice_number_canonical
    total = ctx.total
    if canonical is None or ctx.vendor is None:
        return []
    return [
        r
        for r in ctx.ledger_rows
        if r.invoice_number_canonical == canonical
        and r.total is not None
        and total is not None
        and abs(r.total - total) <= Decimal("1.00")
    ]


@rule("X01_same_file", STAGE)
def x01_same_file(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    if ctx.file_sha256 is None:
        return [e.skip("Same file seen before", "No file fingerprint for this run.")]
    if not ctx.file_rows:
        return [e.passed("New file", "This exact file hasn't been processed before.")]
    first = ctx.file_rows[0]
    result = e.fail(
        ReasonCode.DUPLICATE_SAME_FILE,
        "Same file already processed",
        f"This exact file was already processed as {first.invoice_number or 'an invoice'}, "
        f"{_when(first)}. Reject this copy.",
        severity=Severity.high,
        route=Route.none,
        hint=Outcome.REJECT,
        evidence=_describe(first) | {"matches": [r.run_id for r in ctx.file_rows]},
        at_risk=ctx.total,
    )
    return [ctx.resolve(result, "not_duplicate")]


@rule("X02_same_invoice", STAGE)
def x02_same_invoice(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    if ctx.extraction.invoice_number_canonical is None:
        return [e.skip("Same invoice number", "No invoice number to compare.")]
    if ctx.vendor is None:
        return [e.skip("Same invoice number", "Vendor not identified.")]
    matches = _x02_matches(ctx)
    printed = text_value(ctx.extraction.invoice_number)
    if not matches:
        return [
            e.passed(
                "Invoice number not seen before",
                f"No earlier invoice {printed} from {ctx.vendor.legal_name} for {inr(ctx.total)}.",
            )
        ]
    first = matches[0]
    same_print = first.invoice_number == printed
    how = "" if same_print else f' (printed then as "{first.invoice_number}", now as "{printed}")'
    result = e.fail(
        ReasonCode.DUPLICATE_SAME_INVOICE,
        "Invoice already processed",
        f"This is the same invoice as {first.invoice_number}{how} from {ctx.vendor.legal_name} "
        f"for {inr(first.total)}, {_when(first)}. Paying it again would pay twice.",
        severity=Severity.high,
        route=Route.none,
        hint=Outcome.REJECT,
        evidence=_describe(first)
        | {
            "invoice_number": printed,
            "canonical": ctx.extraction.invoice_number_canonical,
            "matches": [r.run_id for r in matches],
        },  # fmt: skip
        at_risk=ctx.total,
    )
    return [ctx.resolve(result, "not_duplicate")]


def _same_quantities(ctx: RuleContext, row: LedgerEntry) -> bool:
    mine = sorted(ln.quantity for ln in ctx.extraction.line_items if ln.quantity is not None)
    theirs = sorted(b.qty for b in row.billed_lines)
    return bool(mine) and mine == theirs


@rule("X03_fuzzy", STAGE)
def x03_fuzzy(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
    if ctx.vendor is None:
        return [e.skip("Possible duplicate", "Vendor not identified.")]
    total = ctx.total
    inv_date = ctx.invoice_date
    if total is None or inv_date is None:
        return [e.skip("Possible duplicate", "Total or date missing.")]
    pol = ctx.policy.duplicates
    seen = {r.run_id for r in ctx.file_rows} | {r.run_id for r in _x02_matches(ctx)}
    canonical = ctx.extraction.invoice_number_canonical
    po_number = ctx.po.po_number if ctx.po else None
    hits = []
    for r in ctx.ledger_rows:
        if r.run_id in seen or r.total is None or r.invoice_date is None:
            continue
        if total == 0 or abs(r.total - total) / abs(total) * 100 > pol.fuzzy_amount_pct:
            continue
        if abs((r.invoice_date - inv_date).days) > pol.fuzzy_date_window_days:
            continue
        similarity = (
            fuzz.ratio(canonical, r.invoice_number_canonical) / 100
            if canonical and r.invoice_number_canonical
            else 0.0
        )
        same_po = po_number is not None and r.po_number == po_number and _same_quantities(ctx, r)
        if similarity >= pol.fuzzy_similarity or same_po:
            hits.append((r, similarity, same_po))
    if not hits:
        return [
            e.passed("No similar invoice", "No earlier invoice with a similar amount and date.")
        ]
    r, similarity, same_po = hits[0]
    why = (
        "same PO and quantities" if same_po else f"invoice numbers {round(similarity * 100)}% alike"
    )
    result = e.fail(
        ReasonCode.DUPLICATE_SUSPECTED,
        "Looks like an earlier invoice",
        f"Similar to {r.invoice_number or 'an earlier invoice'} dated {r.invoice_date:%d %b %Y} "
        f"for {inr(r.total)} ({why}), {_when(r)}. Check whether it is the same bill.",
        severity=Severity.high,
        route=Route.ap_clerk,
        hint=Outcome.HOLD,
        evidence=_describe(r)
        | {
            "similarity": similarity,
            "same_po_and_quantities": same_po,
            "matches": [h[0].run_id for h in hits],
        },  # fmt: skip
        at_risk=total,
    )
    return [ctx.resolve(result, "not_duplicate")]


RULES = [x01_same_file, x02_same_invoice, x03_fuzzy]
