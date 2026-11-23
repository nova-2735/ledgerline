"""Markdown scorecard for an evaluation run: a one-line verdict, the decision table and field
accuracy against the generator's ground truth."""

from __future__ import annotations

from collections import defaultdict

from .harness import LINE_FIELDS, SCALAR_FIELDS, EvalResult, ScenarioResult

FIELD_LABELS = {
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "supplier_gstin": "Supplier GSTIN",
    "buyer_gstin": "Buyer GSTIN",
    "po_reference": "PO reference",
    "subtotal": "Subtotal",
    "cgst": "CGST",
    "sgst": "SGST",
    "igst": "IGST",
    "total": "Total",
    "bank_account_number": "Bank account",
    "bank_ifsc": "IFSC",
    "line quantity": "Line quantity",
    "line unit_price": "Line unit price",
    "line amount": "Line amount",
}
ROWS = [*SCALAR_FIELDS, *(f"line {k}" for k in LINE_FIELDS)]


def _ratio(ok: int, total: int) -> str:
    if total == 0:
        return "—"
    return f"{ok}/{total} ({ok / total:.1%})"


def field_tally(results: list[ScenarioResult]) -> dict[str, dict[str, tuple[int, int]]]:
    """field → {"digital"|"scanned"|"overall": (correct, total)}."""
    counts: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in results:
        kind = "scanned" if r.render == "scanned" else "digital"
        for f in r.fields:
            for bucket in (kind, "overall"):
                for name in (f.field, "all"):
                    cell = counts[name][bucket]
                    cell[0] += int(f.ok)
                    cell[1] += 1
    return {k: {b: (v[0], v[1]) for b, v in d.items()} for k, d in counts.items()}


def _label(r: ScenarioResult, repeats: bool) -> str:
    return f"{r.doc_id} #{r.repeat}" if repeats else r.doc_id


def _required(r: ScenarioResult) -> str:
    if not r.required:
        return "—"
    present = len(r.required) - len(r.missing)
    text = f"{present}/{len(r.required)}"
    return text + (f" (missing {', '.join(r.missing)})" if r.missing else "")


def _after(r: ScenarioResult) -> str:
    if not r.after_review:
        return "—"
    return "; ".join(f"{s['action']} → {s['actual'] or '—'}" for s in r.after_review)


def render(result: EvalResult) -> str:
    runs = result.results
    total = len(runs)
    tally = field_tally(runs)
    ok_fields, all_fields = tally.get("all", {}).get("overall", (0, 0))
    mark = "✅" if result.correct == total and total else "⚠️"
    lines = [
        f"# Evaluation{' (stress pack)' if result.pack == 'stress' else ''} — "
        f"{result.provider} · {result.model}",
        "",
        f"**{mark} {result.correct} of {total} decisions correct** · invoice fields read "
        f"correctly: {_ratio(ok_fields, all_fields)}.",
        "",
        f"Run on {result.date} · provider `{result.provider}` · model `{result.model}` · "
        f"policy `{result.policy_version}` · "
        + ("fresh model readings (cache bypassed)" if result.force_fresh else "cache allowed")
        + ". Each document starts from a freshly seeded database.",
        "",
    ]
    if result.notes:
        lines += ["Notes:", "", *(f"- {n}" for n in result.notes), ""]

    repeats = any(r.repeat > 1 for r in runs)
    lines += [
        "## Decisions",
        "",
        "| Scenario | Edge case | Expected | Actual | Required codes present | Unexpected codes "
        "| After review | Result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        actual = f"{r.outcome} · {r.route}" if r.outcome else (r.status or "—")
        problem = r.problem
        lines.append(
            f"| {_label(r, repeats)} {r.title} | {r.edge_case or '—'} "
            f"| {r.expected_outcome} · {r.expected_route} | {actual} | {_required(r)} "
            f"| {', '.join(r.unexpected) or '—'} | {_after(r)} "
            f"| {'✓' if problem is None else '✗ ' + problem} |"
        )

    lines += [
        "",
        "## Field accuracy",
        "",
        "Compared with the generator's ground truth after normalisation (dates, amounts and IDs "
        "as the code parses them). A field that is correctly absent counts as correct.",
        "",
        "| Field | Digital | Scanned | Overall |",
        "|---|---|---|---|",
    ]
    for name in [*ROWS, "all"]:
        cells = tally.get(name, {})
        label = "**All fields**" if name == "all" else FIELD_LABELS[name]
        lines.append(
            f"| {label} | {_ratio(*cells.get('digital', (0, 0)))} "
            f"| {_ratio(*cells.get('scanned', (0, 0)))} | {_ratio(*cells.get('overall', (0, 0)))} |"
        )
    wrong = [(r, f) for r in runs for f in r.fields if not f.ok]
    if wrong:
        lines += ["", "Misread fields:", ""]
        for r, f in wrong:
            lines.append(
                f"- {_label(r, repeats)} · {FIELD_LABELS.get(f.field, f.field)}: "
                f"expected `{f.expected}`, read `{f.actual}`"
            )
    lines.append("")
    return "\n".join(lines)
