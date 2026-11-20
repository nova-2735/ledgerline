"""Evaluation harness: every inbox scenario on a fresh copy of a pre-seeded database.

For each scenario the template database is copied into place, the document goes through the real
pipeline, the scenario's `after_review` steps are applied, and the outcome is compared with
`scenarios.yaml`. Extracted fields are compared with the generator's ground truth.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app import db
from app.api.views import run_detail
from app.config import get_settings
from app.decide.policy import active_policy
from app.demo.generate import generate
from app.demo.invoice import load_specs, load_world
from app.demo.seed import load_manifest, seed, world_dir
from app.enums import ActionType, RunSource, StageName
from app.extract.normalize import canonical_po, normalize_gstin, parse_amount
from app.llm.base import LLMClient, get_client
from app.models.api import ReviewRequest
from app.models.extraction import InvoiceExtraction, RawInvoice
from app.models.run import RunDetail
from app.orm import RunRow
from app.pipeline import runner
from app.pipeline.review import ReviewError, apply_review

INBOX = [f"S{i:02d}" for i in range(1, 16)]
RATE_LIMIT_WAITS_S = (30, 60, 120)
SCALAR_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_gstin",
    "buyer_gstin",
    "po_reference",
    "subtotal",
    "cgst",
    "sgst",
    "igst",
    "total",
    "bank_account_number",
    "bank_ifsc",
)
LINE_FIELDS = ("quantity", "unit_price", "amount")


@dataclass
class FieldCheck:
    field: str
    expected: str | None
    actual: str | None

    @property
    def ok(self) -> bool:
        return self.expected == self.actual


@dataclass
class ScenarioResult:
    doc_id: str
    repeat: int
    title: str
    edge_case: str | None
    render: str
    expected_outcome: str
    expected_route: str
    required: list[str]
    allowed: list[str]
    outcome: str | None = None
    route: str | None = None
    reasons: list[str] = field(default_factory=list)
    status: str | None = None
    error: str | None = None
    after_review: list[dict[str, Any]] = field(default_factory=list)
    fields: list[FieldCheck] = field(default_factory=list)
    stage_ms: dict[str, int | None] = field(default_factory=dict)
    llm: dict[str, Any] = field(default_factory=dict)
    rate_limit_retries: int = 0

    @property
    def missing(self) -> list[str]:
        return [c for c in self.required if c not in self.reasons]

    @property
    def unexpected(self) -> list[str]:
        known = set(self.required) | set(self.allowed)
        return [c for c in self.reasons if c not in known]

    @property
    def after_ok(self) -> bool:
        return all(step["actual"] == step["expected"] for step in self.after_review)

    @property
    def problem(self) -> str | None:
        """The first thing that differs from the expectation, or None when correct."""
        if self.error:
            return self.error
        if (self.outcome, self.route) != (self.expected_outcome, self.expected_route):
            return f"got {self.outcome} / {self.route}"
        if self.missing:
            return f"missing {', '.join(self.missing)}"
        if self.unexpected:
            return f"unexpected {', '.join(self.unexpected)}"
        for step in self.after_review:
            if step["actual"] != step["expected"]:
                return f"after {step['action']}: got {step['actual']}"
        return None

    @property
    def correct(self) -> bool:
        return self.problem is None


@dataclass
class EvalResult:
    provider: str
    model: str
    date: str
    force_fresh: bool
    policy_version: str | None
    results: list[ScenarioResult]
    notes: list[str] = field(default_factory=list)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.results if r.correct)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        for r, raw in zip(self.results, data["results"], strict=True):
            raw.update(correct=r.correct, problem=r.problem)
            for f, raw_f in zip(r.fields, raw["fields"], strict=True):
                raw_f["ok"] = f.ok
        data["correct"] = self.correct
        return data


# --- ground truth --------------------------------------------------------------------------------


def _s(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        return format(Decimal(text).normalize(), "f")
    except ArithmeticError:
        return text


def expected_fields(truth: dict[str, Any]) -> dict[str, Any]:
    """What a perfect reading would give, from the generator's numbers (and printed strings for
    the buyer GSTIN, PO reference and subtotal, taken as printed)."""
    exp = truth["expected_values"]
    raw = RawInvoice.model_validate(truth["raw"])
    buyer = normalize_gstin(raw.buyer_gstin)
    out: dict[str, Any] = {k: exp.get(k) for k in SCALAR_FIELDS}
    out["buyer_gstin"] = buyer.value if buyer else None
    out["po_reference"] = canonical_po(raw.po_reference)
    out["subtotal"] = parse_amount(raw.subtotal)  # tax-inclusive invoices print none
    out["lines"] = exp.get("lines", [])
    return out


def actual_fields(ex: InvoiceExtraction) -> dict[str, Any]:
    return {
        "invoice_number": ex.invoice_number.value,
        "invoice_date": ex.invoice_date.value,
        "supplier_gstin": ex.supplier_gstin.value,
        "buyer_gstin": ex.buyer_gstin.value,
        "po_reference": ex.po_reference_canonical,
        "subtotal": ex.subtotal.value,
        "cgst": ex.tax.cgst,
        "sgst": ex.tax.sgst,
        "igst": ex.tax.igst,
        "total": ex.total.value,
        "bank_account_number": ex.bank_account_number.value,
        "bank_ifsc": ex.bank_ifsc.value,
        "lines": [
            {"quantity": ln.quantity, "unit_price": ln.unit_price, "amount": ln.amount}
            for ln in ex.line_items
        ],
    }


def compare_fields(truth: dict[str, Any], ex: InvoiceExtraction | None) -> list[FieldCheck]:
    exp = expected_fields(truth)
    act = actual_fields(ex) if ex is not None else {"lines": []}
    checks = [FieldCheck(k, _s(exp.get(k)), _s(act.get(k))) for k in SCALAR_FIELDS]
    for i, line in enumerate(exp["lines"]):
        got = act["lines"][i] if i < len(act["lines"]) else {}
        for k in LINE_FIELDS:
            checks.append(FieldCheck(f"line {k}", _s(line.get(k)), _s(got.get(k))))
    return checks


# --- running -------------------------------------------------------------------------------------


def _db_file() -> Path:
    url = get_settings().resolved_database_url
    if not url.startswith("sqlite:///"):
        raise RuntimeError("the eval harness needs a SQLite DATABASE_URL")
    return Path(url.removeprefix("sqlite:///"))


def _close_db() -> None:
    runner.shutdown()
    db.reset_caches()


def build_template() -> Path:
    """Generate the world if needed and seed a database; returns the saved template file."""
    world = world_dir()
    if not (world / "manifest.json").is_file():
        generate(world)
    db.init_db()
    seed()
    _close_db()
    template = get_settings().data_dir / "eval_template.db"
    shutil.copyfile(_db_file(), template)
    return template


def restore(template: Path) -> None:
    _close_db()
    target = _db_file()
    for suffix in ("-wal", "-shm"):
        Path(f"{target}{suffix}").unlink(missing_ok=True)
    shutil.copyfile(template, target)


def _detail(run_id: int) -> RunDetail:
    with db.get_sessionmaker()() as session:
        run = session.get(RunRow, run_id)
        assert run is not None
        return run_detail(session, run)


def _failure(run: RunDetail) -> str | None:
    if run.status.value != "failed":
        return None
    broken = next((s for s in run.stages if s.status.value == "error"), None)
    return broken.summary if broken and broken.summary else "the run failed"


def _review(step: dict[str, Any]) -> ReviewRequest:
    return ReviewRequest(
        action=ActionType(step["action"]),
        reviewer=step.get("reviewer", "Eval reviewer"),
        note=step.get("note", "Checked during evaluation"),
        po_number=step.get("po_number"),
        field_corrections=step.get("field_corrections"),
        fields_verified=step.get("fields_verified"),
    )


def run_scenario(
    doc_id: str,
    repeat: int,
    spec_meta: dict[str, Any],
    info: dict[str, Any],
    truth: dict[str, Any],
    client: LLMClient,
    force_fresh: bool,
) -> ScenarioResult:
    exp = spec_meta["expected"]
    result = ScenarioResult(
        doc_id=doc_id,
        repeat=repeat,
        title=spec_meta.get("title") or doc_id,
        edge_case=spec_meta.get("edge_case"),
        render=info["render"],
        expected_outcome=exp["outcome"],
        expected_route=exp["route"],
        required=list(exp.get("required", [])),
        allowed=list(exp.get("allowed", [])),
    )
    email = info.get("email") or {}
    data = (world_dir() / info["file"]).read_bytes()
    run_id = runner.submit(
        data,
        f"{doc_id}.pdf",
        runner.SubmitMeta(
            source=RunSource.demo,
            scenario_id=doc_id,
            sender_name=email.get("sender_name"),
            sender_email=email.get("sender_email"),
            subject=email.get("subject"),
        ),
        force_fresh=force_fresh,
        background=False,
        client=client,
        polish=False,
    )
    run = _detail(run_id)
    result.status = run.status.value
    result.error = _failure(run)
    result.stage_ms = {s.name.value: s.duration_ms for s in run.stages}
    extract = next(s for s in run.stages if s.name == StageName.extract_fields)
    result.llm = {
        k: extract.detail.get(k)
        for k in (
            "provider",
            "model",
            "latency_ms",
            "tokens_in",
            "tokens_out",
            "cached",
            "attempts",
        )
    }
    result.fields = compare_fields(truth, run.extraction)
    if run.decision is None:
        return result
    result.outcome, result.route = run.decision.outcome.value, run.decision.route.value
    result.reasons = [c.value for c in run.decision.reasons]
    for step in exp.get("after_review") or []:
        record = {"action": step["action"], "expected": step["outcome"], "actual": None}
        try:
            apply_review(run_id, _review(step), background=False, client=client, polish=False)
            after = _detail(run_id)
            record["actual"] = after.decision.outcome.value if after.decision else None
        except ReviewError as exc:
            record["actual"] = f"refused ({exc.code})"
        result.after_review.append(record)
    return result


def _rate_limited(result: ScenarioResult) -> bool:
    return bool(result.error and "rate limited" in result.error)


def _budget_spent(result: ScenarioResult) -> bool:
    return bool(result.error and "hourly limit" in result.error)


def run_eval(
    only: list[str] | None = None,
    repeat: int = 1,
    force_fresh: bool = False,
    client: LLMClient | None = None,
    sleep: Any = time.sleep,
) -> EvalResult:
    """Run the scenarios against the configured provider (`LLM_PROVIDER`)."""
    settings = get_settings()
    template = build_template()
    world = world_dir()
    manifest = load_manifest(world)
    specs = {s.id: s.meta for s in load_specs(load_world())}
    client = client or get_client(settings)
    ids = [d for d in INBOX if not only or d in only]
    out = EvalResult(
        provider=client.provider,
        model=client.model,
        date=time.strftime("%Y-%m-%d"),
        force_fresh=force_fresh,
        policy_version=active_policy().policy_version,
        results=[],
    )
    stopped = False
    for doc_id in ids:
        truth = json.loads((world / "truth" / f"{doc_id}.json").read_text(encoding="utf-8"))
        info = manifest["documents"][doc_id]
        for n in range(1, repeat + 1):
            if stopped:
                skipped = run_skipped(doc_id, n, specs[doc_id], info)
                out.results.append(skipped)
                continue
            retries = 0
            while True:
                restore(template)
                result = run_scenario(doc_id, n, specs[doc_id], info, truth, client, force_fresh)
                if not _rate_limited(result) or retries >= len(RATE_LIMIT_WAITS_S):
                    break
                wait = RATE_LIMIT_WAITS_S[retries]
                out.notes.append(f"{doc_id}: rate limited (429); waited {wait} s and retried")
                sleep(wait)
                retries += 1
            result.rate_limit_retries = retries
            out.results.append(result)
            if _budget_spent(result):
                out.notes.append(
                    f"Stopped after {doc_id}: MAX_LIVE_LLM_CALLS_PER_HOUR "
                    f"({settings.max_live_llm_calls_per_hour}) reached"
                )
                stopped = True
    _close_db()
    return out


def run_skipped(
    doc_id: str, repeat: int, meta: dict[str, Any], info: dict[str, Any]
) -> ScenarioResult:
    exp = meta["expected"]
    return ScenarioResult(
        doc_id=doc_id,
        repeat=repeat,
        title=meta.get("title") or doc_id,
        edge_case=meta.get("edge_case"),
        render=info["render"],
        expected_outcome=exp["outcome"],
        expected_route=exp["route"],
        required=list(exp.get("required", [])),
        allowed=list(exp.get("allowed", [])),
        error="not run: live call budget reached",
    )
