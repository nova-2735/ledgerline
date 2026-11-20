"""Rule context, review overrides and helpers for building `CheckResult`s.

Rules are pure functions of the context: they never read the database, the network or the clock.
`build_context` does all the lookups up front.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.decide.policy import Policy
from app.demo.money import format_indian
from app.enums import CheckStatus, Outcome, ReasonCode, Route, Severity, StageName
from app.llm.base import LLMClient
from app.models.checks import CheckResult, POCandidate
from app.models.extraction import DocumentRead, FieldValue, InvoiceExtraction
from app.models.reference import Company, GoodsReceipt, POLineBalance, PurchaseOrder, Vendor
from app.orm import CompanyRow, GoodsReceiptRow
from app.reference.ledger import Ledger, LedgerEntry
from app.reference.loader import company_from_row
from app.reference.purchase_orders import find_by_reference, get_po, infer_candidates
from app.reference.vendors import VendorMatch, resolve_vendor

CENT = Decimal("0.01")
MAX_CANDIDATES = 5

POMethod = Literal[
    "explicit",  # printed reference matched a PO
    "inferred",  # no reference printed; inference found one clear candidate
    "inferred_ref_miss",  # printed reference matched nothing; inference found one
    "not_found",  # printed reference matched nothing; inference found nothing clear
    "ambiguous",  # no reference printed; two or more candidates within the margin
    "missing",  # no reference printed; no candidate reaches the minimum score
]


# --- review overrides ----------------------------------------------------------------------------


class Resolution(BaseModel):
    reviewer: str
    note: str


class ReviewOverrides(BaseModel):
    """What review has established so far; stored on the run and fed back into the rules.

    `field_corrections` are applied to the extraction upstream; they are kept here for the record.
    """

    po_number: str | None = None  # confirmed PO
    bank_verified: bool = False
    fields_verified: bool = False
    not_duplicate: bool = False
    field_corrections: dict[str, str] = {}
    resolutions: dict[str, Resolution] = {}  # override key → who resolved it and why

    def active(self, key: str) -> bool:
        if key == "po_number":
            return self.po_number is not None
        return bool(getattr(self, key))


# --- context -------------------------------------------------------------------------------------


@dataclass
class RuleContext:
    extraction: InvoiceExtraction
    company: Company
    policy: Policy
    today: date
    vendor_match: VendorMatch
    po: PurchaseOrder | None = None
    po_method: POMethod = "missing"
    po_confirmed: bool = False
    po_candidates: list[POCandidate] = field(default_factory=list)
    balances: dict[int, POLineBalance] = field(default_factory=dict)
    grns: list[GoodsReceipt] = field(default_factory=list)
    ledger_rows: list[LedgerEntry] = field(default_factory=list)  # same vendor, within window
    file_rows: list[LedgerEntry] = field(default_factory=list)  # same file
    doc_read: DocumentRead | None = None
    sender_email: str | None = None
    overrides: ReviewOverrides = field(default_factory=ReviewOverrides)
    file_sha256: str | None = None
    run_id: int | None = None
    llm: LLMClient | None = None
    cache: dict[str, Any] = field(default_factory=dict)

    @property
    def vendor(self) -> Vendor | None:
        return self.vendor_match.vendor

    @property
    def total(self) -> Decimal | None:
        return decimal_value(self.extraction.total)

    @property
    def invoice_date(self) -> date | None:
        v = self.extraction.invoice_date.value
        return v if isinstance(v, date) else None

    def cached(self, key: str, build: Callable[[], Any]) -> Any:
        if key not in self.cache:
            self.cache[key] = build()
        return self.cache[key]

    def resolve(self, result: CheckResult, key: str) -> CheckResult:
        """Mark a non-passing result as resolved when review has supplied `key`."""
        if result.status not in (CheckStatus.fail, CheckStatus.warn):
            return result
        if not self.overrides.active(key):
            return result
        res = self.overrides.resolutions.get(key)
        note = f" Resolved by {res.reviewer}: {res.note}" if res else " Resolved by review."
        return result.model_copy(
            update={"resolved_by_review": True, "message": result.message + note}
        )


def decimal_value(fv: FieldValue) -> Decimal | None:
    return fv.value if isinstance(fv.value, Decimal) else None


def text_value(fv: FieldValue) -> str | None:
    v = fv.value
    return v.strip() or None if isinstance(v, str) else None


# --- formatting ----------------------------------------------------------------------------------


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def inr(value: Decimal | None) -> str:
    """₹1,16,348.00 (Indian grouping)."""
    if value is None:
        return "—"
    return f"₹{format_indian(q2(value))}"


def qty(value: Decimal | None) -> str:
    """50, 2.5 — no trailing zeros."""
    if value is None:
        return "—"
    text = format(value.normalize(), "f")
    return text


def pct(value: Decimal) -> str:
    return f"{q2(value)}%"


# --- results -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Emitter:
    """Builds results for one rule, so every result carries the right rule id and stage."""

    rule_id: str
    stage: StageName

    def _make(
        self,
        status: CheckStatus,
        title: str,
        message: str,
        *,
        code: ReasonCode | None = None,
        severity: Severity = Severity.info,
        route: Route = Route.none,
        hint: Outcome | None = None,
        evidence: dict[str, Any] | None = None,
        at_risk: Decimal | None = None,
    ) -> CheckResult:
        return CheckResult(
            rule_id=self.rule_id,
            stage=self.stage,
            status=status,
            code=code,
            severity=severity,
            title=title,
            message=message,
            evidence=evidence or {},
            route=route,
            outcome_hint=hint,
            amount_at_risk=q2(at_risk) if at_risk is not None else None,
        )

    def passed(
        self, title: str, message: str, evidence: dict[str, Any] | None = None
    ) -> CheckResult:
        return self._make(CheckStatus.pass_, title, message, evidence=evidence)

    def skip(self, title: str, message: str, evidence: dict[str, Any] | None = None) -> CheckResult:
        return self._make(CheckStatus.skip, title, message, evidence=evidence)

    def warn(
        self,
        code: ReasonCode,
        title: str,
        message: str,
        *,
        severity: Severity = Severity.info,
        route: Route = Route.none,
        evidence: dict[str, Any] | None = None,
        at_risk: Decimal | None = None,
    ) -> CheckResult:
        return self._make(
            CheckStatus.warn,
            title,
            message,
            code=code,
            severity=severity,
            route=route,
            evidence=evidence,
            at_risk=at_risk,
        )

    def fail(
        self,
        code: ReasonCode,
        title: str,
        message: str,
        *,
        severity: Severity,
        route: Route,
        hint: Outcome | None,
        evidence: dict[str, Any] | None = None,
        at_risk: Decimal | None = None,
    ) -> CheckResult:
        return self._make(
            CheckStatus.fail,
            title,
            message,
            code=code,
            severity=severity,
            route=route,
            hint=hint,
            evidence=evidence,
            at_risk=at_risk,
        )


RuleFn = Callable[[RuleContext, Emitter], list[CheckResult]]


@dataclass(frozen=True)
class Rule:
    rule_id: str
    stage: StageName
    fn: RuleFn

    @property
    def emitter(self) -> Emitter:
        return Emitter(self.rule_id, self.stage)

    def __call__(self, ctx: RuleContext) -> list[CheckResult]:
        results = self.fn(ctx, self.emitter)
        if not results:
            raise RuntimeError(f"rule {self.rule_id} returned no results")
        return results


def rule(rule_id: str, stage: StageName) -> Callable[[RuleFn], Rule]:
    def wrap(fn: RuleFn) -> Rule:
        return Rule(rule_id, stage, fn)

    return wrap


# --- building the context ------------------------------------------------------------------------


def _resolve_po(
    session: Session,
    extraction: InvoiceExtraction,
    vendor_id: str | None,
    policy: Policy,
    ledger: Ledger,
) -> tuple[PurchaseOrder | None, POMethod, list[POCandidate]]:
    printed = extraction.po_reference_canonical
    if printed:
        hit = find_by_reference(session, printed, vendor_id)
        if hit is not None:
            return hit.po, "explicit", []
    candidates = infer_candidates(session, extraction, vendor_id, ledger)
    top = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    reaches = top is not None and top.score >= policy.po_inference.min_score
    clear = reaches and (
        second is None or top.score - second.score >= policy.po_inference.min_margin  # type: ignore[union-attr]
    )
    shown = candidates[:MAX_CANDIDATES]
    if clear and top is not None:
        po = get_po(session, top.po_number)
        return po, ("inferred_ref_miss" if printed else "inferred"), shown
    if printed:
        return None, "not_found", shown
    return None, ("ambiguous" if reaches else "missing"), shown


def build_context(
    session: Session,
    extraction: InvoiceExtraction,
    *,
    policy: Policy,
    today: date,
    doc_read: DocumentRead | None = None,
    sender_email: str | None = None,
    overrides: ReviewOverrides | None = None,
    file_sha256: str | None = None,
    run_id: int | None = None,
    llm: LLMClient | None = None,
) -> RuleContext:
    """Look up everything the rules need: vendor, PO (printed, inferred or confirmed), balances,
    goods receipts and comparable ledger rows."""
    overrides = overrides or ReviewOverrides()
    company_row = session.get(CompanyRow, 1)
    if company_row is None:
        raise LookupError("reference data is not loaded")
    vendor_match = resolve_vendor(session, extraction)
    vendor_id = vendor_match.vendor.vendor_id if vendor_match.vendor else None
    ledger = Ledger(session)

    po, method, candidates = _resolve_po(session, extraction, vendor_id, policy, ledger)
    confirmed = False
    if overrides.po_number:
        chosen = get_po(session, overrides.po_number)
        if chosen is not None:
            po, confirmed = chosen, True

    grns: list[GoodsReceipt] = []
    if po is not None:
        rows = session.scalars(
            select(GoodsReceiptRow)
            .where(GoodsReceiptRow.po_number == po.po_number)
            .order_by(GoodsReceiptRow.received_date, GoodsReceiptRow.grn_number)
        )
        grns = [
            GoodsReceipt(
                grn_number=r.grn_number,
                po_number=r.po_number,
                line_no=r.line_no,
                quantity_received=r.quantity_received,
                received_date=r.received_date,
            )
            for r in rows
        ]

    inv_date = extraction.invoice_date.value
    around = inv_date if isinstance(inv_date, date) else today
    ledger_rows = (
        ledger.ledger_rows_for_vendor(
            vendor_id, policy.duplicates.window_days, around=around, exclude_run_id=run_id
        )
        if vendor_id
        else []
    )
    file_rows = ledger.rows_for_file(file_sha256, exclude_run_id=run_id) if file_sha256 else []

    return RuleContext(
        extraction=extraction,
        company=company_from_row(company_row),
        policy=policy,
        today=today,
        vendor_match=vendor_match,
        po=po,
        po_method=method,
        po_confirmed=confirmed,
        po_candidates=candidates,
        balances=ledger.balance_map(po.po_number) if po else {},
        grns=grns,
        ledger_rows=ledger_rows,
        file_rows=file_rows,
        doc_read=doc_read,
        sender_email=sender_email,
        overrides=overrides,
        file_sha256=file_sha256,
        run_id=run_id,
        llm=llm,
    )
