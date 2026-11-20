"""Transcribe → normalise → ground → score. The model reads; everything after is code."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, NamedTuple

from app.config import Settings, get_settings
from app.llm.base import CallMeta, LLMClient
from app.llm.budget import CallBudget, get_budget
from app.llm.cache import LLMCache, cache_key
from app.llm.prompts import load_prompt
from app.models.extraction import (
    DocumentRead,
    ExtractionMeta,
    FieldValue,
    InvoiceExtraction,
    LineItem,
    RawInvoice,
    TaxSummary,
)

from . import confidence
from .grounding import Grounder, GroundResult, union_bbox
from .normalize import (
    bank_account_valid,
    canonical_invoice_number,
    canonical_po,
    currency_code,
    ifsc_valid,
    invoice_number_valid,
    normalize_account,
    normalize_gstin,
    normalize_ifsc,
    parse_amount,
    parse_date,
    parse_quantity,
    parse_rate,
)
from .words2num import words_to_amount

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")
CRITICAL_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_gstin",
    "total",
    "bank_account_number",
)


@dataclass(frozen=True)
class ExtractEvent:
    """A log line for the extract_fields stage; the pipeline adds run id, seq and time."""

    message: str
    data: dict[str, Any] = field(default_factory=dict)
    type: str = "stage.log"


class ExtractResult(NamedTuple):
    extraction: InvoiceExtraction
    events: list[ExtractEvent]
    detail: dict[str, Any]


# --- field construction ---------------------------------------------------------------------------


def _missing() -> FieldValue:
    conf, level = confidence.missing()
    return FieldValue(
        value=None,
        raw=None,
        confidence=conf,
        level=level,
        grounded="none",
        validators=[],
        bbox=[],
        notes=[],
    )


def _field(
    raw: str | None,
    value: str | Decimal | date | None,
    ground: GroundResult,
    passed: list[str],
    notes: list[str] | None = None,
) -> FieldValue:
    if raw is None or not raw.strip():
        return _missing()
    conf, level = confidence.score(ground.status, bool(passed))
    return FieldValue(
        value=value,
        raw=raw,
        confidence=conf,
        level=level,
        grounded=ground.status,
        validators=passed,
        bbox=ground.bbox,
        notes=notes or [],
    )


def _q2(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def _close(a: Decimal | None, b: Decimal | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= TOLERANCE


# --- tax ----------------------------------------------------------------------------------------


def _tax_summary(raw: RawInvoice) -> tuple[TaxSummary, list[Decimal]]:
    sums = {"CGST": Decimal(), "SGST": Decimal(), "IGST": Decimal(), "other": Decimal()}
    rates: dict[str, set[Decimal]] = {"CGST": set(), "SGST": set(), "IGST": set()}
    for t in raw.tax_lines:
        amount = parse_amount(t.amount) or Decimal()
        rate = parse_rate(t.rate)
        key = t.tax_type if t.tax_type in ("CGST", "SGST", "IGST") else "other"
        sums[key] += amount
        if rate is not None and key in rates:
            rates[key].add(rate)
    effective: set[Decimal] = set(rates["IGST"])
    if rates["CGST"] and len(rates["CGST"]) == len(rates["SGST"]):
        effective |= {
            c + s for c, s in zip(sorted(rates["CGST"]), sorted(rates["SGST"]), strict=True)
        }
    has_intra = bool(sums["CGST"] or sums["SGST"] or rates["CGST"] or rates["SGST"])
    has_inter = bool(sums["IGST"] or rates["IGST"])
    kind = (
        "mixed"
        if has_intra and has_inter
        else "intra"
        if has_intra
        else "inter"
        if has_inter
        else "none"
    )
    total = sums["CGST"] + sums["SGST"] + sums["IGST"] + sums["other"]
    summary = TaxSummary(
        cgst=sums["CGST"],
        sgst=sums["SGST"],
        igst=sums["IGST"],
        other=sums["other"],
        total_tax=total,
        rates_pct=sorted(r.normalize() for r in effective),
        kind=kind,  # type: ignore[arg-type]
    )
    return summary, sorted(effective)


# --- normalisation ------------------------------------------------------------------------------


def normalise(raw: RawInvoice, meta: ExtractionMeta, doc: DocumentRead) -> InvoiceExtraction:
    g = Grounder(doc)
    tax, effective_rates = _tax_summary(raw)
    inclusive = bool(raw.prices_include_tax)
    doc_rate = effective_rates[0] if len(effective_rates) == 1 else None

    # line items
    lines: list[LineItem] = []
    for i, ln in enumerate(raw.line_items):
        qty, unit = parse_quantity(ln.quantity)
        amount = parse_amount(ln.amount)
        rate = parse_rate(ln.tax_rate)
        if rate is None:
            rate = doc_rate
        taxable = amount
        if inclusive and amount is not None and rate is not None:
            taxable = _q2(amount / (1 + rate / 100))
        boxes = g.number(amount).bbox + g.text(ln.description).bbox
        lines.append(
            LineItem(
                index=i,
                description=ln.description,
                item_code=ln.item_code,
                hsn_sac=ln.hsn_sac,
                quantity=qty,
                uom=ln.uom or unit,
                unit_price=parse_amount(ln.unit_price),
                amount=amount,
                tax_rate_pct=rate,
                taxable_amount=taxable,
                bbox=boxes,
            )
        )
    line_sum = sum((ln.amount for ln in lines if ln.amount is not None), Decimal())
    lines_complete = all(ln.amount is not None for ln in lines) and bool(lines)

    other_total = sum((parse_amount(c.amount) or Decimal() for c in raw.other_charges), Decimal())
    subtotal = parse_amount(raw.subtotal)
    round_off = parse_amount(raw.round_off) or Decimal("0.00")
    total = parse_amount(raw.total)
    words_value = words_to_amount(raw.amount_in_words)

    # arithmetic: does the printed total follow from the printed parts?
    if inclusive:
        expected_total = line_sum + other_total + round_off if lines_complete else None
    else:
        base = subtotal if subtotal is not None else (line_sum if lines_complete else None)
        expected_total = (
            base + tax.total_tax + other_total + round_off if base is not None else None
        )
    arithmetic_ok = _close(total, expected_total)
    words_ok = _close(total, words_value)
    subtotal_ok = lines_complete and _close(subtotal, line_sum)

    total_validators = [
        v for v, ok in (("arithmetic", arithmetic_ok), ("words_match", words_ok)) if ok
    ]

    # identifiers
    inv_no = raw.invoice_number.strip() if raw.invoice_number else None
    invoice_number = _field(
        raw.invoice_number,
        inv_no,
        g.text(inv_no),
        ["invoice_number_format"] if invoice_number_valid(inv_no) else [],
    )

    def date_field(text: str | None) -> FieldValue:
        parsed = parse_date(text)
        if parsed is None:
            return _field(text, None, g.text(text), [], ["could not read the date"] if text else [])
        return _field(text, parsed.value, g.date(parsed.value), ["date_valid"], list(parsed.notes))

    def gstin_field(text: str | None) -> FieldValue:
        res = normalize_gstin(text)
        if res is None:
            return _missing()
        ground = g.text(res.value)
        if not ground.found and text:
            ground = g.text(text)
        notes = list(res.notes) + ([] if res.valid else ["GSTIN checksum failed"])
        return _field(text, res.value, ground, ["gstin_checksum"] if res.valid else [], notes)

    def text_field(text: str | None) -> FieldValue:
        value = text.strip() if text else None
        return _field(text, value, g.text(value), [])

    def amount_field(text: str | None, passed: list[str]) -> FieldValue:
        value = parse_amount(text)
        if value is None:
            return _field(
                text, None, g.text(text), [], ["could not read the amount"] if text else []
            )
        return _field(text, value, g.number(value), passed)

    account = normalize_account(raw.bank_account_number)
    ifsc = normalize_ifsc(raw.bank_ifsc)
    account_ground = g.text(account) if account else GroundResult("none")
    if account and not account_ground.found:
        account_ground = g.text(raw.bank_account_number)
    bank_ok = bank_account_valid(account) and ifsc_valid(ifsc)

    words_field = _field(
        raw.amount_in_words,
        words_value,
        g.text(raw.amount_in_words),
        ["words_match"] if words_ok else [],
        [] if words_value is not None or not raw.amount_in_words else ["could not read the words"],
    )

    return InvoiceExtraction(
        doc_type=raw.document_type,
        doc_kind=doc.doc_kind,
        legibility=raw.legibility,
        invoice_number=invoice_number,
        invoice_number_canonical=canonical_invoice_number(inv_no),
        invoice_date=date_field(raw.invoice_date),
        due_date=date_field(raw.due_date),
        supplier_name=text_field(raw.supplier_name),
        supplier_gstin=gstin_field(raw.supplier_gstin),
        supplier_phone=text_field(raw.supplier_phone),
        buyer_name=text_field(raw.buyer_name),
        buyer_gstin=gstin_field(raw.buyer_gstin),
        place_of_supply=text_field(raw.place_of_supply),
        po_reference=text_field(raw.po_reference),
        po_reference_canonical=canonical_po(raw.po_reference),
        currency=currency_code(raw.currency),
        line_items=lines,
        subtotal=amount_field(raw.subtotal, ["arithmetic"] if subtotal_ok else []),
        tax=tax,
        other_charges_total=other_total,
        round_off=amount_field(raw.round_off, ["arithmetic"] if arithmetic_ok else []),
        total=amount_field(raw.total, total_validators),
        amount_in_words=words_field,
        prices_include_tax=inclusive,
        bank_account_number=_field(
            raw.bank_account_number, account, account_ground, ["bank_format"] if bank_ok else []
        ),
        bank_ifsc=_field(
            raw.bank_ifsc, ifsc, g.text(ifsc), ["ifsc_format"] if ifsc_valid(ifsc) else []
        ),
        bank_name=text_field(raw.bank_name),
        annotations=list(raw.annotations),
        meta=meta,
    )


# --- orchestration ------------------------------------------------------------------------------


def _meta_from_call(call: CallMeta, raw: RawInvoice) -> ExtractionMeta:
    return ExtractionMeta(
        provider=call.provider,
        model=call.model,
        prompt_id=call.prompt_id,
        prompt_version=call.prompt_version,
        latency_ms=call.latency_ms,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cached=call.cached,
        cached_at=call.cached_at,
        raw=raw,
    )


def transcribe(
    doc_bytes: bytes,
    doc: DocumentRead,
    client: LLMClient,
    force_fresh: bool = False,
    *,
    settings: Settings | None = None,
    cache: LLMCache | None = None,
    budget: CallBudget | None = None,
) -> tuple[RawInvoice, CallMeta]:
    """Get a RawInvoice from the cache or the model (live calls count against the budget)."""
    settings = settings or get_settings()
    prompt = load_prompt("extract_invoice")
    key = cache_key("extract", doc.sha256, prompt.ref, client.model)
    store = cache or LLMCache()
    if settings.llm_cache and not force_fresh:
        start = time.perf_counter()
        entry = store.get(key)
        if entry is not None:
            saved = entry.response["meta"]
            raw = RawInvoice.model_validate(entry.response["raw"])
            meta = CallMeta(
                provider=saved["provider"],
                model=saved["model"],
                prompt_id=saved["prompt_id"],
                prompt_version=saved["prompt_version"],
                latency_ms=int((time.perf_counter() - start) * 1000),
                input_tokens=saved.get("input_tokens"),
                output_tokens=saved.get("output_tokens"),
                cached=True,
                cached_at=entry.created_at,
            )
            return raw, meta
    if client.is_live:
        (budget or get_budget(settings.max_live_llm_calls_per_hour)).acquire()
    raw, meta = client.extract_invoice(doc_bytes, doc)
    if settings.llm_cache:
        store.put(
            key,
            kind="extract",
            provider=meta.provider,
            model=meta.model,
            prompt_version=meta.prompt_version,
            response={
                "raw": raw.model_dump(mode="json"),
                "meta": {
                    "provider": meta.provider,
                    "model": meta.model,
                    "prompt_id": meta.prompt_id,
                    "prompt_version": meta.prompt_version,
                    "latency_ms": meta.latency_ms,
                    "input_tokens": meta.input_tokens,
                    "output_tokens": meta.output_tokens,
                },
            },
        )
    return raw, meta


def _scalar_fields(ex: InvoiceExtraction) -> dict[str, FieldValue]:
    return {
        name: v for name in type(ex).model_fields if isinstance(v := getattr(ex, name), FieldValue)
    }


def extract(
    doc_bytes: bytes,
    doc_read: DocumentRead,
    client: LLMClient,
    force_fresh: bool = False,
    *,
    settings: Settings | None = None,
    cache: LLMCache | None = None,
    budget: CallBudget | None = None,
) -> ExtractResult:
    raw, call = transcribe(
        doc_bytes, doc_read, client, force_fresh, settings=settings, cache=cache, budget=budget
    )
    extraction = normalise(raw, _meta_from_call(call, raw), doc_read)

    fields = {k: v for k, v in _scalar_fields(extraction).items() if v.raw is not None}
    grounded = sum(1 for v in fields.values() if v.grounded in ("exact", "fuzzy"))
    low = sorted(k for k in CRITICAL_FIELDS if k in fields and fields[k].level.value != "high")
    call_data = {
        "provider": call.provider,
        "model": call.model,
        "prompt": call.prompt_ref,
        "latency_ms": call.latency_ms,
        "tokens_in": call.input_tokens,
        "tokens_out": call.output_tokens,
        "cached": call.cached,
        "attempts": call.attempts,
        "thinking": call.extra.get("thinking"),
    }
    if call.cached:
        when = call.cached_at.isoformat() if call.cached_at else "earlier"
        call_msg = f"Used the saved reading from {when} ({call.provider} · {call.model})"
    else:
        tokens = (
            f" · {call.input_tokens} in / {call.output_tokens} out tokens"
            if call.input_tokens is not None
            else ""
        )
        call_msg = (
            f"Read the document with {call.provider} · {call.model} "
            f"({call.prompt_ref}) in {call.latency_ms} ms{tokens}"
        )
        if call.extra.get("thinking"):
            call_msg += f" · thinking: {call.extra['thinking']}"
    events = [
        ExtractEvent(call_msg, {"llm_call": {"kind": "extract", **call_data}}),
        ExtractEvent(
            f"Found {len(fields)} fields and {len(extraction.line_items)} line items; "
            f"{grounded} located on the page",
            {"fields_grounded": grounded, "fields_total": len(fields), "low_confidence": low},
        ),
    ]
    detail = {**call_data, "fields_grounded": grounded, "fields_total": len(fields)}
    return ExtractResult(extraction, events, detail)


__all__ = [
    "CRITICAL_FIELDS",
    "ExtractEvent",
    "ExtractResult",
    "extract",
    "normalise",
    "transcribe",
    "union_bbox",
]
