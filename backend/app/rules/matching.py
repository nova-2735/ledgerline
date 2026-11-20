"""Line matching (RULES §1.5 and §5, stage `match_lines`) and the Matching view (CONTRACTS §4.8).

The mapping and every per-row check are computed once per context (`analyse`); the M-rules read
their own results from that analysis.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations
from typing import Any, Literal

from app.enums import CheckStatus, MatchType, Outcome, ReasonCode, Route, Severity, StageName
from app.llm.base import LLMError, validate_line_groups
from app.llm.prompts import load_prompt
from app.models.checks import CheckResult, MatchingView, MatchRow
from app.models.extraction import LineItem
from app.models.reference import POLine, POLineBalance, PurchaseOrder
from app.reference.similarity import (
    MATCH_THRESHOLD,
    PairScore,
    description_similarity,
    effective_unit_price,
    pair_score,
)
from app.rules.base import Emitter, Rule, RuleContext, inr, pct, q2, qty, rule
from app.rules.po import vendor_mismatch

STAGE = StageName.match_lines
BUNDLE_TOLERANCE = Decimal("0.005")
BUNDLE_MIN_DESC = 0.5
BUNDLE_SIZES = (2, 3, 4)
BUNDLE_POOL_CAP = 12
HUNDRED = Decimal(100)

MatchedBy = Literal["code", "fuzzy", "bundle", "llm"]


@dataclass
class Mapped:
    kind: Literal["one_to_one", "bundled", "unmatched_invoice", "unmatched_po"]
    invoice: list[int]
    po_lines: list[int]
    matched_by: MatchedBy
    similarity: float | None = None


@dataclass
class Analysis:
    rows: list[Mapped]
    results: dict[str, list[CheckResult]] = field(default_factory=lambda: defaultdict(list))
    row_codes: dict[int, list[CheckResult]] = field(default_factory=lambda: defaultdict(list))
    llm_note: str | None = None
    llm_call: dict[str, Any] | None = None  # `llm_call` event payload of the map_lines call


# --- mapping (RULES §5) --------------------------------------------------------------------------


def _remaining(balances: dict[int, POLineBalance], line_no: int) -> Decimal | None:
    bal = balances.get(line_no)
    return bal.remaining_to_bill if bal else None


def line_value(ln: LineItem) -> Decimal | None:
    """Pre-tax amount of an invoice line."""
    return ln.taxable_amount if ln.taxable_amount is not None else ln.amount


def po_line_value(pl: POLine) -> Decimal:
    return q2(pl.quantity * pl.unit_price)


def _bundle_for(inv: LineItem, pool: list[POLine]) -> tuple[list[POLine], Decimal] | None:
    amount = line_value(inv)
    if amount is None or amount <= 0:
        return None
    best: tuple[Decimal, int, list[int], list[POLine]] | None = None
    candidates = sorted(pool, key=lambda p: p.line_no)[:BUNDLE_POOL_CAP]
    for size in BUNDLE_SIZES:
        for combo in combinations(candidates, size):
            total = sum((po_line_value(p) for p in combo), Decimal())
            diff = abs(total - amount)
            if diff > amount * BUNDLE_TOLERANCE:
                continue
            if not any(_desc(inv, p) >= BUNDLE_MIN_DESC for p in combo):
                continue
            key = (diff, size, [p.line_no for p in combo], list(combo))
            if best is None or key[:3] < best[:3]:
                best = key
    return (best[3], best[0]) if best else None


def _desc(inv: LineItem, pl: POLine) -> float:
    if inv.item_code and inv.item_code.strip().upper() == pl.item_code.strip().upper():
        return 1.0
    return description_similarity(inv.description, pl.description)


def map_lines(
    ctx: RuleContext, po: PurchaseOrder
) -> tuple[list[Mapped], str | None, dict[str, Any] | None]:
    """Rows, a note when the model suggestion failed, and the model call (for the run log)."""
    lines = ctx.extraction.line_items
    by_no = {pl.line_no: pl for pl in po.lines}

    # steps 1–3: pair scores, greedy assignment above the threshold
    scored: list[tuple[float, int, int, PairScore]] = []
    for inv in lines:
        for pl in po.lines:
            ps = pair_score(inv, pl, _remaining(ctx.balances, pl.line_no))
            scored.append((ps.score, inv.index, pl.line_no, ps))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    pairs: dict[int, tuple[int, PairScore]] = {}
    used: set[int] = set()
    for score, i, n, ps in scored:
        if score < MATCH_THRESHOLD or i in pairs or n in used:
            continue
        pairs[i] = (n, ps)
        used.add(n)

    # step 4: bundles, for unmapped lines and lines held only by a wrong-price pair
    bundles: dict[int, list[int]] = {}
    for inv in lines:
        own = pairs.get(inv.index)
        if own is not None and own[1].price != 0:
            continue
        pool = [pl for pl in po.lines if pl.line_no not in used or (own and pl.line_no == own[0])]
        found = _bundle_for(inv, pool)
        if found is None:
            continue
        if own is not None:
            used.discard(own[0])
            del pairs[inv.index]
        bundles[inv.index] = [p.line_no for p in found[0]]
        used.update(bundles[inv.index])

    # step 5: model suggestions for what is still unmapped (never with the fake provider)
    llm_rows: dict[int, Mapped] = {}
    note = None
    call: dict[str, Any] | None = None
    unmapped = [ln.index for ln in lines if ln.index not in pairs and ln.index not in bundles]
    if unmapped and ctx.llm is not None and ctx.llm.is_live:
        prompt = load_prompt("map_lines")
        call = {"kind": "map_lines", "provider": ctx.llm.provider, "model": ctx.llm.model_light,
                "prompt": prompt.ref, "cached": False}  # fmt: skip
        try:
            suggested, meta = ctx.llm.map_lines(ctx.extraction.meta.raw, po)
            call = meta.event_data("map_lines")
            groups = validate_line_groups(suggested, len(lines), list(by_no))
        except LLMError as exc:
            groups = []
            note = f"Line-mapping suggestion unavailable: {exc}"
            call["error"] = str(exc)
        for g in groups:
            if len(g.invoice_lines) != 1 or not g.po_lines:
                continue
            i = g.invoice_lines[0]
            if i not in unmapped or i in llm_rows or any(n in used for n in g.po_lines):
                continue
            if g.kind == "one_to_one" and len(g.po_lines) == 1:
                llm_rows[i] = Mapped("one_to_one", [i], list(g.po_lines), "llm")
            elif g.kind == "bundle" and len(g.po_lines) >= 2:
                llm_rows[i] = Mapped("bundled", [i], sorted(g.po_lines), "llm")
            else:
                continue
            used.update(g.po_lines)
        if call is not None:
            call["accepted_groups"] = len(llm_rows)

    # step 6: assemble rows in invoice order, then the unused PO lines
    rows: list[Mapped] = []
    for inv in lines:
        i = inv.index
        if i in pairs:
            n, ps = pairs[i]
            rows.append(Mapped("one_to_one", [i], [n], "code" if ps.by_code else "fuzzy", ps.desc))
        elif i in bundles:
            sim = max(_desc(inv, by_no[n]) for n in bundles[i])
            rows.append(Mapped("bundled", [i], bundles[i], "bundle", round(sim, 4)))
        elif i in llm_rows:
            rows.append(llm_rows[i])
        else:
            rows.append(Mapped("unmatched_invoice", [i], [], "fuzzy"))
    for pl in po.lines:
        if pl.line_no not in used:
            rows.append(Mapped("unmatched_po", [], [pl.line_no], "fuzzy"))
    return rows, note, call


# --- per-row checks ------------------------------------------------------------------------------

_EMIT = {
    "M01_mapping": Emitter("M01_mapping", STAGE),
    "M02_unit_price": Emitter("M02_unit_price", STAGE),
    "M03_header": Emitter("M03_header", STAGE),
    "M04_po_remaining": Emitter("M04_po_remaining", STAGE),
    "M05_received": Emitter("M05_received", STAGE),
    "M06_tax_rate": Emitter("M06_tax_rate", STAGE),
}


def _prefix(ctx: RuleContext) -> str:
    if (
        ctx.po is not None
        and ctx.po_method in ("inferred", "inferred_ref_miss")
        and not ctx.po_confirmed
    ):
        return f"Against inferred PO {ctx.po.po_number}: "
    return ""


def _gross(rate: Decimal) -> Decimal:
    return 1 + rate / HUNDRED


def _variance(inv: Decimal, po: Decimal) -> Decimal:
    if po == 0:
        return Decimal(0) if inv == 0 else HUNDRED
    return (inv - po) / po * HUNDRED


def _price_result(
    ctx: RuleContext, label: str, inv: Decimal, po: Decimal, q: Decimal, rate: Decimal,
    refs: dict[str, object], unit: str,
) -> CheckResult | None:  # fmt: skip
    """None when the price equals the PO price (counted as a pass)."""
    e = _EMIT["M02_unit_price"]
    v = _variance(inv, po)
    tol = ctx.policy.tolerances.unit_price_pct
    evidence = refs | {
        "expected": str(po),
        "actual": str(inv),
        "delta": str(inv - po),
        "delta_pct": str(q2(v)),
        "tolerance_pct": str(tol),
    }
    p = _prefix(ctx)
    if v == 0:
        return None
    if v < 0:
        return e.warn(
            ReasonCode.PRICE_BELOW_PO,
            "Price below PO",
            f"{p}{label}: {unit} {inr(inv)} is {pct(-v)} below the PO price {inr(po)}.",
            severity=Severity.low,
            route=Route.buyer,
            evidence=evidence,
        )
    if v <= tol:
        return e.warn(
            ReasonCode.PRICE_VARIANCE_WITHIN_TOL,
            "Price slightly above PO (within tolerance)",
            f"{p}{label}: {unit} {inr(inv)} is {pct(v)} above the PO price {inr(po)} "
            f"(tolerance {pct(tol)}).",
            severity=Severity.low,
            route=Route.buyer,
            evidence=evidence,
        )
    at_risk = (inv - po) * q * _gross(rate)
    return e.fail(
        ReasonCode.PRICE_VARIANCE_OVER_TOL,
        "Price above PO",
        f"{p}{label}: {unit} {inr(inv)} is {pct(v)} above the PO price {inr(po)} "
        f"(tolerance {pct(tol)}); {inr(at_risk)} more including GST.",
        severity=Severity.medium,
        route=Route.buyer,
        hint=Outcome.HOLD,
        evidence=evidence,
        at_risk=at_risk,
    )


def _qty_results(
    ctx: RuleContext, po: PurchaseOrder, pl: POLine, billed_qty: Decimal, label: str,
    refs: dict[str, object],
) -> list[CheckResult]:  # fmt: skip
    out: list[CheckResult] = []
    bal = ctx.balances.get(pl.line_no)
    remaining = bal.remaining_to_bill if bal else pl.quantity
    already = bal.billed if bal else Decimal(0)
    p = _prefix(ctx)
    gross = _gross(pl.tax_rate_pct)
    if billed_qty > remaining:
        excess = billed_qty - remaining
        out.append(
            _EMIT["M04_po_remaining"].fail(
                ReasonCode.QTY_EXCEEDS_PO_REMAINING,
                "More than the PO has left",
                f"{p}{label}: billed {qty(billed_qty)} {pl.uom}; the PO ordered "
                f"{qty(pl.quantity)} and {qty(already)} are already billed, so only "
                f"{qty(max(remaining, Decimal(0)))} are left ({qty(excess)} too many).",
                severity=Severity.high,
                route=Route.buyer,
                hint=Outcome.HOLD,
                evidence=refs
                | {
                    "expected": str(remaining),
                    "actual": str(billed_qty),
                    "delta": str(excess),
                    "ordered": str(pl.quantity),
                    "billed_before": str(already),
                },  # fmt: skip
                at_risk=excess * pl.unit_price * gross,
            )
        )
    if po.match_type == MatchType.three_way:
        grns = [g for g in ctx.grns if g.line_no == pl.line_no]
        received = bal.received if bal else Decimal(0)
        unbilled = bal.received_unbilled if bal and bal.received_unbilled is not None else received
        grn_refs = refs | {"grn_numbers": [g.grn_number for g in grns]}
        if not grns:
            out.append(
                _EMIT["M05_received"].fail(
                    ReasonCode.GOODS_NOT_RECEIVED,
                    "Goods not received yet",
                    f"{p}{label}: no goods receipt is recorded for this PO line, so it can't be "
                    "paid until receiving confirms delivery.",
                    severity=Severity.medium,
                    route=Route.receiving,
                    hint=Outcome.HOLD,
                    evidence=grn_refs | {"received": "0"},
                )
            )
        elif billed_qty > unbilled:
            excess = billed_qty - max(unbilled, Decimal(0))
            out.append(
                _EMIT["M05_received"].fail(
                    ReasonCode.QTY_EXCEEDS_RECEIVED,
                    "More than was received",
                    f"{p}{label}: billed {qty(billed_qty)} {pl.uom}; only "
                    f"{qty(max(unbilled, Decimal(0)))} received and not yet billed "
                    f"(received {qty(received)}, billed {qty(already)}).",
                    severity=Severity.medium,
                    route=Route.receiving,
                    hint=Outcome.HOLD,
                    evidence=grn_refs
                    | {
                        "expected": str(unbilled),
                        "actual": str(billed_qty),
                        "delta": str(excess),
                        "received": str(received),
                        "billed_before": str(already),
                    },  # fmt: skip
                    at_risk=excess * pl.unit_price * gross,
                )
            )
    return out


def _tax_rate_result(
    ctx: RuleContext, inv: LineItem, pl: POLine, label: str, refs: dict[str, object]
) -> CheckResult | None:
    if inv.tax_rate_pct is None or inv.tax_rate_pct == pl.tax_rate_pct:
        return None
    return _EMIT["M06_tax_rate"].fail(
        ReasonCode.TAX_RATE_MISMATCH,
        "GST rate differs from PO",
        f"{_prefix(ctx)}{label}: GST charged at {qty(inv.tax_rate_pct)}%, but the PO line is "
        f"at {qty(pl.tax_rate_pct)}%.",
        severity=Severity.medium,
        route=Route.buyer,
        hint=Outcome.HOLD,
        evidence=refs | {"expected": str(pl.tax_rate_pct), "actual": str(inv.tax_rate_pct)},
    )


def _label(inv: LineItem) -> str:
    return f'Line {inv.index + 1} "{inv.description}"'


def analyse(ctx: RuleContext) -> Analysis:
    return ctx.cached("matching", lambda: _analyse(ctx))  # type: ignore[no-any-return]


def _analyse(ctx: RuleContext) -> Analysis:
    po = ctx.po
    assert po is not None
    rows, note, call = map_lines(ctx, po)
    a = Analysis(rows=rows, llm_note=note, llm_call=call)
    lines = {ln.index: ln for ln in ctx.extraction.line_items}
    by_no = {pl.line_no: pl for pl in po.lines}
    price_ok = qty_ok = received_ok = tax_ok = 0

    for r_index, row in enumerate(rows):
        if row.kind not in ("one_to_one", "bundled"):
            continue
        inv = lines[row.invoice[0]]
        refs: dict[str, object] = {
            "po_number": po.po_number,
            "line_no": row.po_lines[0] if len(row.po_lines) == 1 else row.po_lines,
            "invoice_line": inv.index + 1,
        }
        label = _label(inv)
        found: list[CheckResult] = []
        if row.kind == "one_to_one":
            pl = by_no[row.po_lines[0]]
            inv_price = effective_unit_price(inv)
            if inv_price is not None:
                res = _price_result(ctx, label, inv_price, pl.unit_price,
                                    inv.quantity or Decimal(0), pl.tax_rate_pct, refs,
                                    "unit price")  # fmt: skip
                if res:
                    found.append(res)
            billed = inv.quantity if inv.quantity is not None else Decimal(0)
            found += _qty_results(ctx, po, pl, billed, label, refs)
            tax = _tax_rate_result(ctx, inv, pl, label, refs)
            if tax:
                found.append(tax)
        else:
            bundled = [by_no[n] for n in row.po_lines]
            expected = sum((po_line_value(p) for p in bundled), Decimal())
            amount = line_value(inv)
            if amount is not None:
                rate = bundled[0].tax_rate_pct
                res = _price_result(ctx, label, amount, expected, Decimal(1), rate, refs, "amount")
                if res:
                    found.append(res)
            for part in bundled:
                found += _qty_results(
                    ctx, po, part, part.quantity, label, refs | {"line_no": part.line_no}
                )
                tax = _tax_rate_result(ctx, inv, part, label, refs | {"line_no": part.line_no})
                if tax:
                    found.append(tax)
        for res in found:
            a.results[res.rule_id].append(res)
        a.row_codes[r_index] = found
        ids = {f.rule_id for f in found}
        price_ok += "M02_unit_price" not in ids
        qty_ok += "M04_po_remaining" not in ids
        received_ok += "M05_received" not in ids
        tax_ok += "M06_tax_rate" not in ids

    _mapping_results(ctx, a, lines)
    _header_result(ctx, a)
    mapped = sum(1 for r in rows if r.kind in ("one_to_one", "bundled"))
    p = _prefix(ctx)
    if mapped == 0:
        for rid in ("M02_unit_price", "M04_po_remaining", "M05_received", "M06_tax_rate"):
            a.results[rid].append(_EMIT[rid].skip("Line checks", "No invoice line maps to the PO."))
        return a
    if price_ok:
        a.results["M02_unit_price"].append(
            _EMIT["M02_unit_price"].passed(
                "Prices match PO", f"{p}{price_ok}/{mapped} lines at the PO price."
            )
        )
    if qty_ok:
        a.results["M04_po_remaining"].append(
            _EMIT["M04_po_remaining"].passed(
                "Quantities within PO", f"{p}{qty_ok}/{mapped} lines within what the PO has left."
            )
        )
    if po.match_type == MatchType.three_way:
        if received_ok:
            a.results["M05_received"].append(
                _EMIT["M05_received"].passed(
                    "Goods received", f"{p}{received_ok}/{mapped} lines covered by goods receipts."
                )
            )
    else:
        a.results["M05_received"].append(
            _EMIT["M05_received"].skip("Goods received", "Two-way PO: no goods receipt needed.")
        )
    if tax_ok:
        a.results["M06_tax_rate"].append(
            _EMIT["M06_tax_rate"].passed("GST rates match PO", f"{p}{tax_ok}/{mapped} lines.")
        )
    return a


def _mapping_results(ctx: RuleContext, a: Analysis, lines: dict[int, LineItem]) -> None:
    e = _EMIT["M01_mapping"]
    po = ctx.po
    assert po is not None
    by_no = {pl.line_no: pl for pl in po.lines}
    p = _prefix(ctx)
    misc = ctx.policy.tolerances.misc_charge_abs
    for r_index, row in enumerate(a.rows):
        if row.kind == "bundled":
            inv = lines[row.invoice[0]]
            parts = " + ".join(f"line {n} {inr(po_line_value(by_no[n]))}" for n in row.po_lines)
            res = e.warn(
                ReasonCode.LINES_BUNDLED,
                "One invoice line covers several PO lines",
                f"{p}{_label(inv)} ({inr(line_value(inv))}) covers PO {parts}.",
                evidence={
                    "po_number": po.po_number,
                    "po_lines": row.po_lines,
                    "invoice_line": inv.index + 1,
                    "matched_by": row.matched_by,
                },  # fmt: skip
            )
        elif row.kind == "unmatched_invoice":
            inv = lines[row.invoice[0]]
            amount = line_value(inv)
            refs = {"po_number": po.po_number, "invoice_line": inv.index + 1,
                    "actual": str(amount) if amount is not None else None}  # fmt: skip
            if amount is not None and amount <= misc:
                res = e.warn(
                    ReasonCode.MISC_CHARGE_ALLOWED,
                    "Small charge not on the PO",
                    f"{p}{_label(inv)} ({inr(amount)}) is not on the PO but is under the "
                    f"{inr(misc)} allowance for small charges.",
                    severity=Severity.low,
                    route=Route.buyer,
                    evidence=refs,
                )
            else:
                res = e.fail(
                    ReasonCode.LINE_NOT_ON_PO,
                    "Line not on the PO",
                    f"{p}{_label(inv)} ({inr(amount)}) doesn't match anything on {po.po_number}. "
                    "The buyer needs to amend the PO or the vendor must remove it.",
                    severity=Severity.medium,
                    route=Route.buyer,
                    hint=Outcome.HOLD,
                    evidence=refs,
                )
        else:
            continue
        a.results["M01_mapping"].append(res)
        a.row_codes[r_index].append(res)
    if not a.results["M01_mapping"]:
        mapped = sum(1 for r in a.rows if r.kind == "one_to_one")
        a.results["M01_mapping"].append(
            e.passed("Every line is on the PO", f"{p}All {mapped} invoice lines map to PO lines.")
        )


def _row_expected(row: Mapped, inv: LineItem, by_no: dict[int, POLine]) -> tuple[Decimal, Decimal]:
    """(expected pre-tax amount, PO tax rate) for a mapped row."""
    if row.kind == "bundled":
        bundled = [by_no[n] for n in row.po_lines]
        return sum((po_line_value(p) for p in bundled), Decimal()), bundled[0].tax_rate_pct
    pl = by_no[row.po_lines[0]]
    return q2(pl.unit_price * (inv.quantity or Decimal(0))), pl.tax_rate_pct


def header_totals(
    ctx: RuleContext, rows: list[Mapped]
) -> tuple[Decimal | None, Decimal | None, Decimal]:
    """(Σ expected, Σ invoiced, amount at risk incl. GST) over mapped rows."""
    po = ctx.po
    assert po is not None
    by_no = {pl.line_no: pl for pl in po.lines}
    lines = {ln.index: ln for ln in ctx.extraction.line_items}
    expected = invoiced = Decimal()
    at_risk = Decimal()
    count = 0
    for row in rows:
        if row.kind not in ("one_to_one", "bundled"):
            continue
        inv = lines[row.invoice[0]]
        amount = line_value(inv)
        if amount is None:
            continue
        exp, rate = _row_expected(row, inv, by_no)
        expected += exp
        invoiced += amount
        at_risk += (amount - exp) * _gross(rate)
        count += 1
    if not count:
        return None, None, Decimal()
    return expected, invoiced, abs(at_risk)


def _header_result(ctx: RuleContext, a: Analysis) -> None:
    e = _EMIT["M03_header"]
    expected, invoiced, at_risk = header_totals(ctx, a.rows)
    if expected is None or invoiced is None:
        a.results["M03_header"].append(e.skip("Invoice vs PO value", "No line maps to the PO."))
        return
    tol = ctx.policy.tolerances
    limit = min(tol.header_pct / HUNDRED * expected, tol.header_abs)
    delta = invoiced - expected
    evidence = {
        "po_number": ctx.po.po_number if ctx.po else None,
        "expected": str(expected),
        "actual": str(invoiced),
        "delta": str(delta),
        "delta_pct": str(q2(_variance(invoiced, expected))),
        "limit": str(q2(limit)),
    }
    p = _prefix(ctx)
    if abs(delta) > limit:
        a.results["M03_header"].append(
            e.fail(
                ReasonCode.AMOUNT_VARIANCE_OVER_TOL,
                "Invoice value differs from PO",
                f"{p}The matched lines come to {inr(invoiced)} before GST against {inr(expected)} "
                f"at PO prices, a difference of {inr(abs(delta))} "
                f"(allowed {inr(limit)}); {inr(at_risk)} including GST.",
                severity=Severity.medium,
                route=Route.buyer,
                hint=Outcome.HOLD,
                evidence=evidence,
                at_risk=at_risk,
            )
        )
        return
    a.results["M03_header"].append(
        e.passed(
            "Invoice value fits the PO",
            f"{p}Matched lines {inr(invoiced)} vs {inr(expected)} at PO prices "
            f"(difference {inr(abs(delta))}, allowed {inr(limit)}).",
            evidence,
        )
    )


# --- rules ---------------------------------------------------------------------------------------


def skip_reason(ctx: RuleContext) -> str | None:
    if ctx.po is None:
        return "No PO resolved, so lines can't be matched."
    if vendor_mismatch(ctx):
        return "PO belongs to a different vendor."
    return None


def _from_analysis(rule_id: str, title: str) -> Rule:
    def fn(ctx: RuleContext, e: Emitter) -> list[CheckResult]:
        reason = skip_reason(ctx)
        if reason:
            return [e.skip(title, reason)]
        return list(analyse(ctx).results[rule_id])

    return rule(rule_id, STAGE)(fn)


m01_mapping = _from_analysis("M01_mapping", "Lines on the PO")
m02_unit_price = _from_analysis("M02_unit_price", "Prices vs PO")
m03_header = _from_analysis("M03_header", "Invoice vs PO value")
m04_po_remaining = _from_analysis("M04_po_remaining", "Quantities within PO")
m05_received = _from_analysis("M05_received", "Goods received")
m06_tax_rate = _from_analysis("M06_tax_rate", "GST rates vs PO")

RULES = [m01_mapping, m02_unit_price, m03_header, m04_po_remaining, m05_received, m06_tax_rate]


# --- matching view -------------------------------------------------------------------------------


def _status(results: list[CheckResult]) -> tuple[CheckStatus, list[ReasonCode]]:
    codes = [r.code for r in results if r.code is not None and r.status != CheckStatus.pass_]
    if any(r.status == CheckStatus.fail for r in results):
        return CheckStatus.fail, codes
    if codes:
        return CheckStatus.warn, codes
    return CheckStatus.pass_, codes


def build_view(ctx: RuleContext) -> MatchingView:
    """The Matching tab: rows, header totals and PO candidates."""
    po = ctx.po
    if skip_reason(ctx) is not None or po is None:
        return MatchingView(
            po_number=po.po_number if po else None,
            match_type=po.match_type if po else None,
            rows=[],
            header_expected=None,
            header_invoiced=None,
            header_variance=None,
            po_candidates=ctx.po_candidates,
        )
    a = analyse(ctx)
    lines = {ln.index: ln for ln in ctx.extraction.line_items}
    by_no = {pl.line_no: pl for pl in po.lines}
    three_way = po.match_type == MatchType.three_way
    rows: list[MatchRow] = []
    for r_index, row in enumerate(a.rows):
        status, codes = _status(a.row_codes.get(r_index, []))
        inv = lines[row.invoice[0]] if row.invoice else None
        pls = [by_no[n] for n in row.po_lines]
        bal = ctx.balances.get(pls[0].line_no) if len(pls) == 1 else None
        amount = line_value(inv) if inv else None
        expected: Decimal | None = None
        variance: Decimal | None = None
        inv_price = po_price = None
        if row.kind == "one_to_one" and inv is not None:
            inv_price = effective_unit_price(inv)
            po_price = pls[0].unit_price
            expected, _ = _row_expected(row, inv, by_no)
            if inv_price is not None:
                variance = q2(_variance(inv_price, po_price))
        elif row.kind == "bundled" and inv is not None:
            expected, _ = _row_expected(row, inv, by_no)
            if amount is not None:
                variance = q2(_variance(amount, expected))
        if row.kind == "unmatched_po":
            status = CheckStatus.skip
        available = None
        if bal is not None:
            available = bal.received_unbilled if three_way else bal.remaining_to_bill
        rows.append(
            MatchRow(
                invoice_line_indexes=row.invoice,
                po_line_nos=row.po_lines,
                kind=row.kind,
                description_invoice=inv.description if inv else None,
                description_po=" + ".join(p.description for p in pls) if pls else None,
                similarity=row.similarity,
                qty_invoiced=inv.quantity if inv else None,
                qty_ordered=pls[0].quantity if len(pls) == 1 else None,
                qty_received=(bal.received if bal and three_way else None),
                qty_billed_before=bal.billed if bal else None,
                qty_available=available,
                unit_price_invoice=inv_price,
                unit_price_po=po_price,
                price_variance_pct=variance,
                amount_invoice=amount,
                amount_expected=expected,
                status=status,
                codes=codes,
                matched_by=row.matched_by,
            )
        )
    exp_total, inv_total, _ = header_totals(ctx, a.rows)
    return MatchingView(
        po_number=po.po_number,
        match_type=po.match_type,
        rows=rows,
        header_expected=exp_total,
        header_invoiced=inv_total,
        header_variance=(inv_total - exp_total)
        if exp_total is not None and inv_total is not None
        else None,
        po_candidates=ctx.po_candidates,
    )
