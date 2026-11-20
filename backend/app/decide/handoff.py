"""Handoff templates (RULES §4): one question for the owner, a suggested action, the allowed
review actions and which draft (vendor email / internal note) the case needs.

Templates are `str.format` strings filled from the primary check's evidence and the run's facts,
so a missing value fails loudly in tests instead of printing a blank.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from app.demo.money import format_indian
from app.enums import ActionType, ReasonCode, Route
from app.models.checks import CheckResult
from app.models.decision import Handoff
from app.models.extraction import InvoiceExtraction
from app.models.reference import POLine, PurchaseOrder, Vendor
from app.rules.base import RuleContext, decimal_value, inr, q2, qty, text_value

A = ActionType
C = ReasonCode
HUNDRED = Decimal(100)

# Codes whose failing check carries an amount that counts as exposure (RULES §8).
AT_RISK_CODES = frozenset(
    {
        C.DUPLICATE_SAME_FILE,
        C.DUPLICATE_SAME_INVOICE,
        C.DUPLICATE_SUSPECTED,
        C.BANK_DETAILS_CHANGED,
        C.VENDOR_NOT_FOUND,
        C.VENDOR_BLOCKED,
        C.QTY_EXCEEDS_PO_REMAINING,
        C.QTY_EXCEEDS_RECEIVED,
        C.PRICE_VARIANCE_OVER_TOL,
        C.AMOUNT_VARIANCE_OVER_TOL,
    }
)

ROUTE_LABELS = {
    Route.none: "no one",
    Route.ap_clerk: "AP clerk",
    Route.buyer: "buyer",
    Route.receiving: "receiving team",
    Route.treasury: "treasury",
    Route.procurement: "procurement",
    Route.controller: "finance controller",
    Route.vendor: "vendor",
}


def amount_at_risk(active: list[CheckResult]) -> Decimal | None:
    """Run-level exposure: the largest amount at risk among the counted failing checks."""
    values = [
        c.amount_at_risk for c in active if c.code in AT_RISK_CODES and c.amount_at_risk is not None
    ]
    return max(values) if values else None


# --- facts ---------------------------------------------------------------------------------------


@dataclass
class Facts:
    """What templates may mention about the run, independent of any one check."""

    extraction: InvoiceExtraction
    vendor: Vendor | None = None
    po: PurchaseOrder | None = None
    po_vendor_name: str | None = None
    ctx: RuleContext | None = None
    approval_limit: Decimal = Decimal(0)
    company_name: str = "Kestrel Foods Pvt. Ltd."
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(cls, extraction: InvoiceExtraction, ctx: RuleContext | None, limit: Decimal) -> Facts:
        if ctx is None:
            return cls(extraction, approval_limit=limit)
        return cls(
            extraction,
            vendor=ctx.vendor,
            po=ctx.po,
            po_vendor_name=ctx.po_vendor_name,
            ctx=ctx,
            approval_limit=limit,
            company_name=ctx.company.name,
        )

    @property
    def supplier_name(self) -> str:
        return text_value(self.extraction.supplier_name) or "The supplier"

    @property
    def vendor_name(self) -> str:
        return self.vendor.legal_name if self.vendor else self.supplier_name

    @property
    def number(self) -> str | None:
        return text_value(self.extraction.invoice_number)

    @property
    def invoice_date(self) -> date | None:
        v = self.extraction.invoice_date.value
        return v if isinstance(v, date) else None

    @property
    def total(self) -> Decimal | None:
        return decimal_value(self.extraction.total)

    def po_line(self, line_no: Any) -> POLine | None:
        if self.po is None or not isinstance(line_no, int):
            return None
        return next((ln for ln in self.po.lines if ln.line_no == line_no), None)

    def base_values(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor_name,
            "supplier_name": self.supplier_name,
            "number": self.number or "(no number)",
            "total": inr(self.total),
            "po": self.po.po_number if self.po else "the PO",
            "limit": format_indian(q2(self.approval_limit)),
        }


def fmt_date(value: Any) -> str:
    if isinstance(value, date):
        return f"{value:%d %b %Y}"
    if isinstance(value, str) and value:
        try:
            return f"{date.fromisoformat(value[:10]):%d %b %Y}"
        except ValueError:
            return value
    return "an earlier date"


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


# --- per-code values -----------------------------------------------------------------------------

Values = Callable[[CheckResult, Facts, list[CheckResult]], dict[str, Any]]


def _bank(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    inv = c.evidence.get("invoice", {})
    on_file = c.evidence.get("on_file", {})
    return {
        "new_masked": inv.get("account") or "a new account",
        "new_bank": inv.get("bank_name") or "another bank",
        "phone_on_file": on_file.get("phone") or "on file",
        "phone_invoice": inv.get("phone") or "not printed",
    }


def _candidates(c: CheckResult) -> list[dict[str, Any]]:
    return list(c.evidence.get("candidates") or [])


def _po_inferred(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    cands = _candidates(c)
    po_number = c.evidence.get("po_number") or (cands[0]["po_number"] if cands else "the PO")
    top = next((x for x in cands if x["po_number"] == po_number), cands[0] if cands else {})
    po = f.po if f.po and f.po.po_number == po_number else None
    return {
        "po": po_number,
        "buyer": po.buyer_name if po else "buyer unknown",
        "po_date": fmt_date(po.po_date) if po else "date unknown",
        "k": len(cands),
        "score": f"{float(top.get('score', 0)):.2f}",
    }


def _po_ambiguous(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    cands = _candidates(c) + [{"po_number": "another PO"}] * 2
    return {"po_a": cands[0]["po_number"], "po_b": cands[1]["po_number"]}


def _po_missing(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    return {"buyer_or_procurement": "the buyer" if f.vendor else "procurement"}


def _available(c: CheckResult, f: Facts) -> tuple[Decimal, Decimal, POLine | None]:
    """(quantity that can be paid now, quantity billed) for a quantity check."""
    billed = _dec(c.evidence.get("actual"))
    line_no = c.evidence.get("line_no")
    pl = f.po_line(line_no)
    remaining = _dec(c.evidence.get("expected"))
    available = remaining
    if f.ctx is not None and pl is not None:
        bal = f.ctx.balances.get(pl.line_no)
        if bal is not None:
            available = bal.remaining_to_bill
            if bal.received_unbilled is not None:
                available = min(available, bal.received_unbilled)
    return max(available, Decimal(0)), billed, pl


def _qty_remaining(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    available, billed, pl = _available(c, f)
    price = pl.unit_price if pl else Decimal(0)
    rate = pl.tax_rate_pct if pl else Decimal(0)
    return {
        "qty": qty(billed),
        "uom": pl.uom if pl else "units",
        "po": c.evidence.get("po_number", "the PO"),
        "n": c.evidence.get("line_no", "?"),
        "remaining": qty(_dec(c.evidence.get("expected"))),
        "available": qty(available),
        "partial_amount": inr(available * price * (1 + rate / HUNDRED)),
        "excess": qty(billed - available),
    }


def _qty_received(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    return {
        "po": c.evidence.get("po_number", "the PO"),
        "n": c.evidence.get("line_no", "?"),
        "received": qty(_dec(c.evidence.get("received"))),
    }


def _price(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    inv, po = _dec(c.evidence.get("actual")), _dec(c.evidence.get("expected"))
    quantity = Decimal(1)
    index = c.evidence.get("invoice_line")
    if c.code == C.PRICE_VARIANCE_OVER_TOL and isinstance(index, int):
        lines = f.extraction.line_items
        if 0 < index <= len(lines) and lines[index - 1].quantity is not None:
            quantity = lines[index - 1].quantity or Decimal(1)
    delta = (inv - po) * quantity
    return {
        "inv_price": inr(inv),
        "po_price": inr(po),
        "pct": c.evidence.get("delta_pct", "?"),
        "delta": inr(delta),
        "delta_incl_tax": inr(c.amount_at_risk if c.amount_at_risk is not None else delta),
    }


def _tax_type(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    split = c.evidence.get("expected_cgst_sgst_each") or {}
    if split:
        parts = []
        for rate, half in split.items():
            h = Decimal(str(rate)) / 2
            amount = inr(Decimal(str(half)))
            parts.append(f"CGST {h:g}% {amount} + SGST {h:g}% {amount}")
        expected = "; ".join(parts)
    elif c.evidence.get("expected") == "IGST":
        expected = "IGST instead of CGST + SGST"
    else:
        expected = "CGST + SGST instead of IGST"
    return {"expected_taxes": expected}


_MISSING_LABELS = {
    C.FIELD_MISSING_INVOICE_NUMBER: "an invoice number",
    C.FIELD_MISSING_INVOICE_DATE: "an invoice date",
    C.FIELD_MISSING_TOTAL: "the invoice total",
    C.FIELD_MISSING_SUPPLIER: "the supplier's name and GSTIN",
}


def _missing(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    labels = [_MISSING_LABELS[x.code] for x in active if x.code in _MISSING_LABELS]
    labels = labels or [_MISSING_LABELS.get(c.code, "the missing details")]  # type: ignore[arg-type]
    return {"missing_fields": " and ".join(dict.fromkeys(labels))}


def _duplicate(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    e = c.evidence
    outcome = (e.get("original_outcome") or "processed").lower()
    outcome = {"approve": "approved", "hold": "held"}.get(outcome, outcome)
    return {
        "original_number": e.get("original_invoice_number") or "an earlier invoice",
        "original_outcome": outcome,
        "original_date": fmt_date(e.get("processed_at") or e.get("original_date")),
        "original_run": e.get("display_id") or f"run {e.get('run_id')}",
        "original_total": inr(_dec(e.get("original_total"))) if e.get("original_total") else "—",
    }


def _vendor_not_found(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    clause = ""
    if f.po is not None and any(x.code == C.PO_VENDOR_MISMATCH for x in active):
        clause = (
            f"; it quotes {f.po.po_number}, which belongs to {f.po_vendor_name or f.po.vendor_id}"
        )
    return {"po_clause": clause}


def _blocked(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    return {"block_reason": c.evidence.get("block_reason") or "see vendor master"}


def _low_confidence(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    fields = [x.get("label", x.get("field", "")) for x in c.evidence.get("fields", [])]
    return {"fields": ", ".join(fields) or "the highlighted fields"}


def _proforma(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    secondary = ""
    if any(x.code == C.LINE_NOT_ON_PO for x in active):
        secondary = (
            "; note: the buyer will also need to amend the PO for the lines that aren't on it"
        )
    return {"secondary": secondary}


def _none(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    return {}


def _generic(c: CheckResult, f: Facts, active: list[CheckResult]) -> dict[str, Any]:
    return {"message": c.message, "owner": ROUTE_LABELS.get(c.route, "reviewer")}


# --- templates -----------------------------------------------------------------------------------

Draft = Literal["vendor", "internal"] | None


@dataclass(frozen=True)
class Template:
    question: str
    action: str
    actions: tuple[ActionType, ...]
    values: Values
    draft: Draft = None
    internal_to: Route | None = None
    short_reason: str = "correction needed"
    vendor_ask: str = ""  # the vendor email's request, a format string


_VENDOR_Q = "Send this back to {vendor} for a corrected invoice?"

TEMPLATES: dict[ReasonCode, Template] = {
    C.BANK_DETAILS_CHANGED: Template(
        "Did {vendor} really change their bank account to {new_masked} ({new_bank})?",
        "Call {vendor} on the number on file ({phone_on_file}) — not the number on this invoice "
        "({phone_invoice}) — and confirm. Update the vendor master through change control before "
        "any payment.",
        (A.verify_bank, A.reject),
        _bank,
        draft="internal",
        internal_to=Route.treasury,
    ),
    C.PO_INFERRED: Template(
        "Is this invoice for {po} ({buyer}, {po_date})? It's the best fit among {k} open POs for "
        "{vendor} (score {score}).",
        "Confirm the PO to continue matching.",
        (A.confirm_po, A.reject),
        _po_inferred,
    ),
    C.PO_AMBIGUOUS: Template(
        "Which PO is this invoice for: {po_a} or {po_b}?",
        "Pick the PO; matching will re-run.",
        (A.confirm_po, A.reject),
        _po_ambiguous,
    ),
    C.PO_MISSING: Template(
        "There's no purchase order that fits this invoice. Was this purchase approved?",
        "Ask {buyer_or_procurement} to raise or point to a PO.",
        (A.confirm_po, A.reject),
        _po_missing,
        draft="internal",
        internal_to=Route.buyer,
    ),
    C.QTY_EXCEEDS_PO_REMAINING: Template(
        "{vendor} billed {qty} {uom} on {po} line {n}, but only {remaining} remain on the PO and "
        "{available} are received and unbilled. Pay {available} now?",
        "Approve {available} {uom} ({partial_amount} incl. tax) and request a credit note for "
        "{excess}.",
        (A.approve, A.send_to_vendor, A.reject),
        _qty_remaining,
        draft="vendor",
        short_reason="credit note requested",
        vendor_ask="We can pay {available} {uom} on {po} line {n} now ({partial_amount} incl. "
        "GST); the other {excess} {uom} aren't covered by the order and the goods we have "
        "received. Please send a credit note for {excess} {uom}.",
    ),
    C.QTY_EXCEEDS_RECEIVED: Template(
        "Has the rest of {po} line {n} arrived? We've only recorded {received} received.",
        "Ask receiving to post the GRN, or hold until delivery.",
        (A.approve, A.reject),
        _qty_received,
        draft="internal",
        internal_to=Route.receiving,
    ),
    C.PRICE_VARIANCE_OVER_TOL: Template(
        "{vendor} billed {inv_price} vs PO {po_price} ({pct}% higher, {delta} + tax). Was a price "
        "change agreed?",
        "Approve at invoice price if agreed, else request a credit note of {delta_incl_tax}.",
        (A.approve, A.send_to_vendor),
        _price,
        draft="vendor",
        short_reason="price above PO",
        vendor_ask="The price billed ({inv_price}) is {pct}% above our PO price ({po_price}). "
        "Unless our buyer agreed the change, please send a credit note for {delta_incl_tax}.",
    ),
    C.TAX_TYPE_MISMATCH: Template(
        _VENDOR_Q,
        "Request a revised invoice with {expected_taxes}; IGST on an intra-state supply can't be "
        "claimed as input credit.",
        (A.send_to_vendor,),
        _tax_type,
        draft="vendor",
        short_reason="wrong GST type",
        vendor_ask="The GST type doesn't match the place of supply, so we can't claim input tax "
        "credit. Please send a revised invoice with {expected_taxes}.",
    ),
    C.FIELD_MISSING_INVOICE_NUMBER: Template(
        _VENDOR_Q,
        "Request a GST-compliant tax invoice that shows {missing_fields}.",
        (A.send_to_vendor, A.correct_fields),
        _missing,
        draft="vendor",
        short_reason="missing details",
        vendor_ask="The invoice doesn't show {missing_fields}. Please send a GST-compliant tax "
        "invoice that includes it.",
    ),
    C.DUPLICATE_SAME_INVOICE: Template(
        "This matches {original_number} from {vendor}, {original_outcome} on {original_date} "
        "({original_run}). Reject this copy?",
        "Reject; tell the vendor it's already been processed.",
        (A.reject, A.not_duplicate),
        _duplicate,
        draft="vendor",
        short_reason="already processed",
        vendor_ask="This matches invoice {original_number}, which we already processed on "
        "{original_date}, so we won't pay it again. Please let us know if it is for a different "
        "supply.",
    ),
    C.DUPLICATE_SUSPECTED: Template(
        "Is this the same bill as {original_number} ({original_date}, {original_total})?",
        "Compare the two; reject if same.",
        (A.not_duplicate, A.reject),
        _duplicate,
    ),
    C.VENDOR_NOT_FOUND: Template(
        "{supplier_name} isn't in the vendor master{po_clause}. Should it be onboarded?",
        "Send to procurement for onboarding checks; don't pay until approved.",
        (A.reject, A.approve),
        _vendor_not_found,
        draft="internal",
        internal_to=Route.procurement,
    ),
    C.VENDOR_BLOCKED: Template(
        "{vendor} is blocked in the vendor master. Keep this invoice rejected?",
        "Don't pay. Vendor blocked: {block_reason}.",
        (A.reopen,),
        _blocked,
    ),
    C.FIELD_LOW_CONFIDENCE: Template(
        "Please check {fields} against the highlighted areas of the scan.",
        "Verify or correct the highlighted values.",
        (A.correct_fields,),
        _low_confidence,
    ),
    C.APPROVAL_LIMIT_EXCEEDED: Template(
        "Approve payment of {total} to {vendor}? Everything matches; it's above the ₹{limit} "
        "auto-approval limit.",
        "Controller approval.",
        (A.approve, A.reject),
        _none,
    ),
    C.DOC_PROFORMA: Template(
        _VENDOR_Q,
        "Proforma invoices aren't payable; ask {vendor} for the tax invoice{secondary}.",
        (A.send_to_vendor,),
        _proforma,
        draft="vendor",
        short_reason="tax invoice needed",
        vendor_ask="This is a proforma invoice, which we can't pay. Please send the tax invoice"
        "{secondary}.",
    ),
}
# Codes that share a template (RULES §4 groups them).
for _alias, _base in (
    (C.PO_NOT_FOUND, C.PO_MISSING),
    (C.GOODS_NOT_RECEIVED, C.QTY_EXCEEDS_RECEIVED),
    (C.AMOUNT_VARIANCE_OVER_TOL, C.PRICE_VARIANCE_OVER_TOL),
    (C.FIELD_MISSING_INVOICE_DATE, C.FIELD_MISSING_INVOICE_NUMBER),
    (C.FIELD_MISSING_TOTAL, C.FIELD_MISSING_INVOICE_NUMBER),
    (C.FIELD_MISSING_SUPPLIER, C.FIELD_MISSING_INVOICE_NUMBER),
    (C.DUPLICATE_SAME_FILE, C.DUPLICATE_SAME_INVOICE),
):
    TEMPLATES[_alias] = TEMPLATES[_base]

_GENERIC_VENDOR = Template(
    _VENDOR_Q,
    "Ask {vendor} for a corrected invoice: {message}",
    (A.send_to_vendor, A.correct_fields),
    _generic,
    draft="vendor",
    vendor_ask="We can't process it yet: {message} Please send a corrected invoice.",
)
_GENERIC_INTERNAL = Template(
    "{message} Can this go ahead?",
    "The {owner} should review and approve or reject.",
    (A.approve, A.reject),
    _generic,
)
_GENERIC_REJECT = Template(
    "{message} Keep this rejected?",
    "Don't pay.",
    (A.reopen,),
    _generic,
)


def template_for(check: CheckResult) -> Template:
    if check.code in TEMPLATES:
        return TEMPLATES[check.code]  # type: ignore[index]
    if check.route == Route.vendor:
        return _GENERIC_VENDOR
    if check.route == Route.none:
        return _GENERIC_REJECT
    return _GENERIC_INTERNAL


def template_values(check: CheckResult, facts: Facts, active: list[CheckResult]) -> dict[str, Any]:
    t = template_for(check)
    return facts.base_values() | t.values(check, facts, active)


@dataclass(frozen=True)
class HandoffPlan:
    handoff: Handoff
    template: Template
    values: dict[str, Any]


def build_handoff(
    primary: CheckResult, active: list[CheckResult], facts: Facts, owner: Route
) -> HandoffPlan:
    """Handoff for the primary check; `active` are the unresolved failing checks."""
    t = template_for(primary)
    values = template_values(primary, facts, active)
    blocking = list(dict.fromkeys(c.code for c in active if c.code is not None))
    handoff = Handoff(
        owner=owner,
        question=t.question.format_map(values),
        suggested_action=t.action.format_map(values),
        actions=list(t.actions),
        amount_at_risk=amount_at_risk(active),
        blocking_codes=blocking,
    )
    return HandoffPlan(handoff, t, values)
