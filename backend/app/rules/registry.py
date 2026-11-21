"""Ordered rule registry and stage runner.

`run_all` runs every stage in order and keeps going after failures, so the reviewer sees the full
picture. Only DOC_NOT_INVOICE or DOC_UNREADABLE stop early: the vendor, tax, PO, matching and
duplicate stages then return `skip` results (RULES §1.8).
"""

from __future__ import annotations

from app.enums import CheckStatus, ReasonCode, StageName
from app.models.checks import CheckResult
from app.rules import document, duplicates, matching, po, tax, vendor
from app.rules.base import Rule, RuleContext

STAGE_RULES: dict[StageName, list[Rule]] = {
    StageName.validate_document: document.RULES,
    StageName.identify_vendor: vendor.RULES,
    StageName.check_tax: tax.RULES,
    StageName.resolve_po: po.RULES,
    StageName.match_lines: matching.RULES,
    StageName.check_duplicates: duplicates.RULES,
}
STAGES = list(STAGE_RULES)
STOPPING_CODES = frozenset(
    {ReasonCode.DOC_NOT_INVOICE, ReasonCode.DOC_UNREADABLE, ReasonCode.DOC_MULTIPLE_INVOICES}
)
# A credit or debit note adjusts an earlier invoice: it is booked against the vendor's account,
# not matched to a purchase order, so only the PO and line-matching stages are skipped.
PARTIAL_SKIPS: dict[ReasonCode, tuple[StageName, ...]] = {
    ReasonCode.DOC_CREDIT_NOTE: (StageName.resolve_po, StageName.match_lines),
}


def all_rules() -> list[Rule]:
    return [r for rules in STAGE_RULES.values() for r in rules]


def run_stage(stage: StageName, ctx: RuleContext) -> list[CheckResult]:
    out: list[CheckResult] = []
    for r in STAGE_RULES[stage]:
        out.extend(r(ctx))
    return out


def stops_pipeline(results: list[CheckResult]) -> ReasonCode | None:
    for r in results:
        if r.status == CheckStatus.fail and not r.resolved_by_review and r.code in STOPPING_CODES:
            return r.code
    return None


def skipped_stage(stage: StageName, reason: str) -> list[CheckResult]:
    return [r.emitter.skip(r.rule_id, reason) for r in STAGE_RULES[stage]]


def skip_reason_for(code: ReasonCode) -> str:
    if code == ReasonCode.DOC_UNREADABLE:
        return "Skipped: the document can't be read."
    if code == ReasonCode.DOC_MULTIPLE_INVOICES:
        return "Skipped: the file holds more than one invoice; each must be processed on its own."
    if code == ReasonCode.DOC_CREDIT_NOTE:
        return "Skipped: a credit or debit note is applied to the vendor's account, not to a PO."
    return "Skipped: the document is not an invoice."


def skips_after(results: list[CheckResult]) -> dict[StageName, str]:
    """Later stages to skip, with the reason, given the `validate_document` results."""
    stop = stops_pipeline(results)
    if stop is not None:
        return {s: skip_reason_for(stop) for s in STAGES[1:]}
    out: dict[StageName, str] = {}
    for r in results:
        if r.status == CheckStatus.fail and not r.resolved_by_review and r.code in PARTIAL_SKIPS:
            for stage in PARTIAL_SKIPS[r.code]:
                out[stage] = skip_reason_for(r.code)
    return out


def run_all(ctx: RuleContext) -> dict[StageName, list[CheckResult]]:
    """Results per stage, in pipeline order."""
    results: dict[StageName, list[CheckResult]] = {}
    skips: dict[StageName, str] = {}
    for stage in STAGES:
        if stage in skips:
            results[stage] = skipped_stage(stage, skips[stage])
            continue
        results[stage] = run_stage(stage, ctx)
        if stage == StageName.validate_document:
            skips = skips_after(results[stage])
    return results


def flatten(results: dict[StageName, list[CheckResult]]) -> list[CheckResult]:
    return [r for stage in STAGES for r in results.get(stage, [])]
