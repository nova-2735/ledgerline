"""The eleven pipeline stages (PLAN §3). Each reads and extends a `RunState`; the wrapper in
`run_stage` emits `stage.started` → `stage.log`* → `stage.completed` and records the stage state.

Rules never stop the pipeline; only DOC_NOT_INVOICE / DOC_UNREADABLE make stages 5–9 `skipped`
(RULES §1.8). Decide and explain always run.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app import clock
from app.decide.decision import evaluate, is_active
from app.decide.policy import Policy
from app.enums import CheckStatus, ConfidenceLevel, StageName, StageStatus
from app.extract.confidence import HUMAN_VERIFIED_VALIDATOR
from app.extract.extractor import extract, normalise
from app.ingest.reader import read_bytes
from app.llm.base import LLMClient
from app.models.checks import CheckResult, MatchingView
from app.models.decision import Decision
from app.models.extraction import DocumentRead, FieldValue, InvoiceExtraction, RawInvoice
from app.models.run import StageState
from app.rules import matching
from app.rules.base import (
    ReviewOverrides,
    RuleContext,
    build_context,
    inr,
    set_money_currency,
    text_value,
)
from app.rules.matching import skip_reason
from app.rules.registry import STAGES as RULE_STAGES
from app.rules.registry import run_stage as run_rules
from app.rules.registry import skipped_stage, skips_after

from .events import emit

STAGE_ORDER: list[StageName] = list(StageName)


def stage_index(stage: StageName) -> int:
    return STAGE_ORDER.index(stage)


# Fields a reviewer can correct: printed strings that the extractor normalises.
CORRECTABLE_FIELDS: frozenset[str] = frozenset(
    name
    for name, info in InvoiceExtraction.model_fields.items()
    if info.annotation in (FieldValue, "FieldValue") and name in RawInvoice.model_fields
)


@dataclass
class RunState:
    """Everything one execution of a run needs and produces."""

    run_id: int
    session: Session
    filename: str
    sha256: str
    data: bytes
    page_count: int
    client: LLMClient
    policy: Policy
    sender_email: str | None = None
    force_fresh: bool = False
    polish: bool | None = None
    overrides: ReviewOverrides = field(default_factory=ReviewOverrides)
    doc_read: DocumentRead | None = None
    extraction: InvoiceExtraction | None = None
    ctx: RuleContext | None = None
    results: dict[StageName, list[CheckResult]] = field(default_factory=dict)
    skips: dict[StageName, str] = field(default_factory=dict)  # stage → why it is skipped
    matching: MatchingView | None = None
    decision: Decision | None = None
    decision_version: int = 1
    stages: dict[StageName, StageState] = field(default_factory=dict)
    cached_extraction: bool = False
    persist: Callable[[RunState], None] | None = None
    llm_calls: list[dict[str, Any]] = field(default_factory=list)  # polish calls of `decide`

    def log(self, stage: StageName, message: str, data: dict[str, Any] | None = None) -> None:
        emit(self.run_id, "stage.log", stage, StageStatus.running, message, data)

    @property
    def checks(self) -> list[CheckResult]:
        return [c for s in STAGE_ORDER for c in self.results.get(s, [])]


@dataclass
class StageResult:
    summary: str
    checks: list[CheckResult] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    status: StageStatus | None = None  # default: derived from the checks


def pending(name: StageName) -> StageState:
    return StageState(
        name=name,
        status=StageStatus.pending,
        started_at=None,
        finished_at=None,
        duration_ms=None,
        summary=None,
        check_rule_ids=[],
        detail={},
    )


def status_from_checks(checks: list[CheckResult]) -> StageStatus:
    if any(is_active(c) for c in checks):
        return StageStatus.failed
    if any(c.status in (CheckStatus.warn, CheckStatus.fail) for c in checks):
        return StageStatus.warned
    if checks and all(c.status == CheckStatus.skip for c in checks):
        return StageStatus.skipped
    return StageStatus.passed


def run_stage(
    state: RunState, name: StageName, fn: Callable[[RunState], StageResult], *, silent: bool = False
) -> StageResult:
    """Run one stage. `silent` re-evaluates a stage kept from an earlier pass (after a review)
    without emitting events, so its checks reflect the review but its timings stay as they were."""
    previous = state.stages.get(name)
    started = clock.now()
    if not silent:
        state.stages[name] = pending(name).model_copy(
            update={"status": StageStatus.running, "started_at": started}
        )
        emit(state.run_id, "stage.started", name, StageStatus.running)
    t0 = time.perf_counter()
    result = fn(state)
    duration = int((time.perf_counter() - t0) * 1000)
    status = result.status or status_from_checks(result.checks)
    if name in RULE_STAGES or name == StageName.decide:
        state.results[name] = result.checks
    rule_ids = [c.rule_id for c in result.checks]
    if silent and previous is not None:
        state.stages[name] = previous.model_copy(
            update={
                "status": status,
                "summary": result.summary,
                "check_rule_ids": rule_ids,
                "detail": result.detail,
            }
        )
        return result
    state.stages[name] = StageState(
        name=name,
        status=status,
        started_at=started,
        finished_at=clock.now(),
        duration_ms=duration,
        summary=result.summary,
        check_rule_ids=rule_ids,
        detail=result.detail,
    )
    if state.persist is not None:
        state.persist(state)
    emit(
        state.run_id,
        "stage.completed",
        name,
        status,
        result.summary,
        {
            "duration_ms": duration,
            "check_rule_ids": rule_ids,
            "checks": [c.model_dump(mode="json") for c in result.checks],
            "detail": result.detail,
        },
    )
    return result


# --- 1–3: intake, read, extract ------------------------------------------------------------------


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def intake(state: RunState) -> StageResult:
    size = len(state.data)
    kb = max(1, round(size / 1024))
    return StageResult(
        f"Received {state.filename} — {_plural(state.page_count, 'page')}, {kb} KB.",
        detail={"bytes": size, "pages": state.page_count, "sha256": state.sha256},
        status=StageStatus.passed,
    )


def read_document(state: RunState) -> StageResult:
    doc = read_bytes(state.data)
    state.doc_read = doc
    pages = [
        {
            "kind": p.kind.value,
            "words": len(p.words),
            "ocr_used": p.ocr_used,
            "ocr_mean_conf": p.ocr_mean_conf,
        }
        for p in doc.pages
    ]
    scanned = [p for p in doc.pages if p.kind.value != "digital"]
    if not scanned:
        how = "digital document with a text layer"
    elif any(p.ocr_used for p in scanned):
        how = "scanned document; text recognised with OCR"
    else:
        how = "scanned document; OCR isn't available, so the model reads the image"
    for p in scanned:
        state.log(
            StageName.read_document,
            f"Page {p.index + 1} is a scanned image"
            + (f" (OCR confidence {p.ocr_mean_conf:.0f}%)" if p.ocr_mean_conf else ""),
        )
    return StageResult(
        f"Read {_plural(doc.page_count, 'page')}: {how}.",
        detail={"doc_kind": doc.doc_kind.value, "pages": pages},
        status=StageStatus.passed,
    )


def ensure_doc_read(state: RunState) -> DocumentRead:
    if state.doc_read is None:
        state.doc_read = read_bytes(state.data)
    return state.doc_read


def extract_fields(state: RunState) -> StageResult:
    result = extract(state.data, ensure_doc_read(state), state.client, state.force_fresh)
    for ev in result.events:
        state.log(StageName.extract_fields, ev.message, ev.data)
    state.extraction = apply_corrections(result.extraction, state.overrides, state.doc_read)
    state.cached_extraction = result.extraction.meta.cached
    ex = state.extraction
    set_money_currency(ex.currency)
    number = text_value(ex.invoice_number)
    supplier = text_value(ex.supplier_name) or "an unnamed supplier"
    total = ex.total.value if isinstance(ex.total.value, Decimal) else None
    what = f"invoice {number}" if number else "an invoice with no invoice number"
    summary = f"Read {what} from {supplier}" + (f", total {inr(total)}." if total else ".")
    return StageResult(summary, detail=result.detail, status=StageStatus.passed)


def apply_corrections(
    extraction: InvoiceExtraction, overrides: ReviewOverrides, doc: DocumentRead | None
) -> InvoiceExtraction:
    """Re-normalise the transcription with reviewer corrections (strings as the reviewer typed
    them), then mark the corrected fields as verified."""
    corrections = {k: v for k, v in overrides.field_corrections.items() if k in CORRECTABLE_FIELDS}
    if not corrections or doc is None:
        return extraction
    raw = extraction.meta.raw.model_copy(update=corrections)
    fixed = normalise(raw, extraction.meta, doc)  # meta keeps the model's own transcription
    updates: dict[str, FieldValue] = {}
    for name in corrections:
        fv: FieldValue = getattr(fixed, name)
        updates[name] = fv.model_copy(
            update={
                "confidence": 1.0,
                "level": ConfidenceLevel.high,
                "validators": list(dict.fromkeys([*fv.validators, HUMAN_VERIFIED_VALIDATOR])),
                "notes": [*fv.notes, "Corrected by reviewer"],
            }
        )
    return fixed.model_copy(update=updates)


def as_transcribed(extraction: InvoiceExtraction, doc: DocumentRead) -> InvoiceExtraction:
    """The extraction as the model read it, before any reviewer correction."""
    return normalise(extraction.meta.raw, extraction.meta, doc)


def _slot(c: CheckResult) -> tuple[str, object]:
    return c.rule_id, c.evidence.get("field")


def keep_corrected_findings(
    corrected: list[CheckResult], original: list[CheckResult], ctx: RuleContext
) -> list[CheckResult]:
    """Findings a field correction fixed stay on record: the original failing check, marked
    resolved by the reviewer with their note, replaces the pass it now produces (RULES §3: review
    never deletes a check)."""
    still = {(c.rule_id, c.code) for c in corrected if c.status == CheckStatus.fail}
    fixed: dict[tuple[str, object], list[CheckResult]] = {}
    for c in original:
        if c.status == CheckStatus.fail and (c.rule_id, c.code) not in still:
            fixed.setdefault(_slot(c), []).append(ctx.resolve(c, "field_corrections"))
    out: list[CheckResult] = []
    for c in corrected:
        slot = _slot(c)
        if slot not in fixed:
            out.append(c)
            continue
        if c.status != CheckStatus.pass_:
            out.append(c)  # a new finding in the same place stays
        out.extend(fixed.pop(slot, []))
    for rest in fixed.values():
        out.extend(rest)
    return out


# --- 4–9: rule stages ----------------------------------------------------------------------------

PASS_SUMMARY: dict[StageName, Callable[[RuleContext], str]] = {
    StageName.validate_document: lambda ctx: (
        "Tax invoice with all required fields; arithmetic and dates check out."
    ),
    StageName.identify_vendor: lambda ctx: (
        f"Matched {ctx.vendor.legal_name} ({ctx.vendor.vendor_id}) in the vendor master."
        if ctx.vendor
        else "Vendor checked."
    ),
    StageName.check_tax: lambda ctx: "GSTINs, GST type, rates and amounts are correct.",
    StageName.resolve_po: lambda ctx: (
        f"Invoice is against {ctx.po.po_number}." if ctx.po else "Purchase order checked."
    ),
    StageName.match_lines: lambda ctx: (
        f"Every line matches {ctx.po.po_number}"
        + (" and the goods receipts." if ctx.po.match_type.value == "three_way" else ".")
        if ctx.po
        else "Lines checked."
    ),
    StageName.check_duplicates: lambda ctx: "No earlier copy of this invoice found.",
}


def rule_summary(stage: StageName, checks: list[CheckResult], ctx: RuleContext) -> str:
    active = [c for c in checks if is_active(c)]
    noted = [
        c for c in checks if c.status in (CheckStatus.warn, CheckStatus.fail) and c not in active
    ]
    if active:
        more = f" (+{len(active) - 1} more)" if len(active) > 1 else ""
        return f"{active[0].title}{more}."
    if checks and all(c.status == CheckStatus.skip for c in checks):
        return checks[0].message
    if noted:
        resolved = [c for c in noted if c.resolved_by_review]
        if resolved and len(resolved) == len(noted):
            return f"{resolved[0].title} — resolved by review."
        return f"Passed with a note: {noted[0].title.lower()}."
    return PASS_SUMMARY[stage](ctx)


def ensure_context(state: RunState) -> RuleContext:
    if state.ctx is None:
        if state.extraction is None:
            raise RuntimeError("no extraction to check")
        state.ctx = build_context(
            state.session,
            state.extraction,
            policy=state.policy,
            today=clock.today(),
            doc_read=state.doc_read,
            sender_email=state.sender_email,
            overrides=state.overrides,
            file_sha256=state.sha256,
            run_id=state.run_id,
            llm=state.client,
        )
    return state.ctx


PO_METHOD = {
    "explicit": "explicit",
    "inferred": "inferred",
    "inferred_ref_miss": "inferred",
    "ambiguous": "ambiguous",
    "not_found": "none",
    "missing": "none",
}


def _stage_detail(stage: StageName, state: RunState, checks: list[CheckResult]) -> dict[str, Any]:
    ctx = ensure_context(state)
    if stage == StageName.identify_vendor:
        return {
            "vendor_id": ctx.vendor.vendor_id if ctx.vendor else None,
            "matched_by": ctx.vendor_match.matched_by,
        }
    if stage == StageName.resolve_po:
        method = "confirmed" if ctx.po_confirmed else PO_METHOD[ctx.po_method]
        return {
            "po_number": ctx.po.po_number if ctx.po else None,
            "method": method,
            "candidates": [c.model_dump(mode="json") for c in ctx.po_candidates],
        }
    if stage == StageName.match_lines:
        view = matching.build_view(ctx)
        state.matching = view
        return {
            "match_type": view.match_type.value if view.match_type else None,
            "rows": [r.model_dump(mode="json") for r in view.rows],
        }
    if stage == StageName.check_duplicates:
        matches: list[int] = []
        for c in checks:
            if c.status == CheckStatus.fail:
                matches.extend(m for m in c.evidence.get("matches", []) if m not in matches)
        return {"compared": len(ctx.ledger_rows) + len(ctx.file_rows), "matches": matches}
    return {}


def rule_stage(stage: StageName) -> Callable[[RunState], StageResult]:
    def fn(state: RunState) -> StageResult:
        ctx = ensure_context(state)
        if stage in state.skips:
            checks = skipped_stage(stage, state.skips[stage])
            if stage == StageName.match_lines:
                state.matching = matching.build_view(ctx)
            return StageResult(checks[0].message, checks, {}, StageStatus.skipped)
        checks = run_rules(stage, ctx)
        if stage == StageName.validate_document:
            if state.overrides.field_corrections:
                original = as_transcribed(ctx.extraction, ensure_doc_read(state))
                before = run_rules(stage, dataclasses.replace(ctx, extraction=original, cache={}))
                checks = keep_corrected_findings(checks, before, ctx)
            state.skips = skips_after(checks)
        detail = _stage_detail(stage, state, checks)
        if stage == StageName.match_lines and skip_reason(ctx) is None:
            call = matching.analyse(ctx).llm_call
            if call is not None:
                state.log(stage, _call_message(call, "Asked the model to suggest line matches"),
                          {"llm_call": call})  # fmt: skip
        return StageResult(rule_summary(stage, checks, ctx), checks, detail)

    return fn


# --- 10–11: decide, explain ----------------------------------------------------------------------


def decide(state: RunState) -> StageResult:
    ctx = ensure_context(state)
    prior = [c for s in RULE_STAGES for c in state.results.get(s, [])]
    result = evaluate(
        prior,
        ctx.extraction,
        state.policy,
        state.decision_version,
        ctx=ctx,
        decided_at=clock.now(),
        client=state.client,
        polish=state.polish,
    )
    state.decision = result.decision
    state.llm_calls = list(result.llm_calls)
    own = [c for c in result.checks if c.stage == StageName.decide]
    d = result.decision
    return StageResult(
        d.headline,
        own,
        {"outcome": d.outcome.value, "policy_version": d.policy_version},
    )


def explain_route(state: RunState) -> StageResult:
    d = state.decision
    if d is None:
        raise RuntimeError("no decision to explain")
    ex = d.explanation
    for call in state.llm_calls:
        if call.get("accepted"):
            lead = "Reworded the summary with"
        else:
            lead = "Kept the template summary; the model's rewording wasn't used"
        state.log(StageName.explain_route, _call_message(call, lead), {"llm_call": call})
    if d.handoff is not None:
        summary = f"Sent to {d.route.value.replace('_', ' ')}: {d.handoff.question}"
        if not d.handoff.question:
            summary = f"Sent to {d.route.value.replace('_', ' ')}: {d.handoff.suggested_action}"
    elif d.posting is not None:
        summary = (
            f"Posting ready: {_plural(len(d.posting.lines), 'line')}, due "
            f"{_fmt_date(d.posting.due_date)}."
        )
    else:
        summary = ex.summary
    detail: dict[str, Any] = {"generated_by": ex.generated_by}
    if ex.vendor_message is not None:
        detail["vendor_message"] = True
    if ex.internal_note is not None:
        detail["internal_note"] = ex.internal_note.to
    return StageResult(summary, [], detail, StageStatus.passed)


def _call_message(call: dict[str, Any], lead: str) -> str:
    """One log line for a model call: who, which prompt, how long, how many tokens."""
    where = f"{call.get('provider')} · {call.get('model')} ({call.get('prompt')})"
    if call.get("error"):
        return f"{lead}: {where} failed — {call['error']}"
    tokens = (
        f" · {call['tokens_in']} in / {call['tokens_out']} out tokens"
        if call.get("tokens_in") is not None
        else ""
    )
    why = f" ({call['rejected_because']})" if call.get("rejected_because") else ""
    return f"{lead}{why}: {where} in {call.get('latency_ms')} ms{tokens}"


def _fmt_date(d: date) -> str:
    return d.strftime("%d %b %Y").lstrip("0")


STAGE_FUNCS: dict[StageName, Callable[[RunState], StageResult]] = {
    StageName.intake: intake,
    StageName.read_document: read_document,
    StageName.extract_fields: extract_fields,
    **{s: rule_stage(s) for s in RULE_STAGES},
    StageName.decide: decide,
    StageName.explain_route: explain_route,
}
