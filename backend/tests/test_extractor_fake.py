from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app import db
from app.config import get_settings
from app.demo.generate import generate
from app.enums import ConfidenceLevel, DocKind
from app.extract.extractor import CRITICAL_FIELDS, extract
from app.ingest.reader import read_bytes
from app.llm.base import BudgetExceededError, FakeProviderError, get_client
from app.llm.budget import CallBudget
from app.llm.fake import FakeClient
from app.models.extraction import DocumentRead, RawInvoice


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("world")
    generate(out)
    return out


def _doc(world: Path, doc_id: str) -> tuple[bytes, DocumentRead]:
    folder = "inbox" if doc_id.startswith("S") else "history"
    data = (world / folder / f"{doc_id}.pdf").read_bytes()
    return data, read_bytes(data)


class CountingFake(FakeClient):
    def __init__(self, truth_dir: Path, live: bool = False) -> None:
        super().__init__(get_settings(), truth_dir=truth_dir)
        self.calls = 0
        self.is_live = live

    def extract_invoice(self, pdf_bytes: bytes, doc: DocumentRead) -> tuple[RawInvoice, object]:  # type: ignore[override]
        self.calls += 1
        return super().extract_invoice(pdf_bytes, doc)


@pytest.fixture
def client(world: Path) -> CountingFake:
    db.init_db()
    return CountingFake(world / "truth")


def test_get_client_is_fake_in_tests() -> None:
    assert isinstance(get_client(get_settings()), FakeClient)


def test_s01_critical_fields_exact_and_high(world: Path, client: CountingFake) -> None:
    data, doc = _doc(world, "S01")
    ex = extract(data, doc, client).extraction
    for name in CRITICAL_FIELDS:
        fv = getattr(ex, name)
        assert fv.grounded == "exact", name
        assert fv.level is ConfidenceLevel.high, name
        assert fv.bbox and fv.bbox[0].page == 0, name
    assert ex.invoice_number.value == "SPI/26-27/0214"
    assert ex.invoice_number_canonical == "2627214"
    assert ex.po_reference_canonical == "142"
    assert str(ex.invoice_date.value) == "2026-11-12"
    assert ex.total.value == Decimal("116348.00")
    assert set(ex.total.validators) == {"arithmetic", "words_match"}
    assert ex.supplier_gstin.validators == ["gstin_checksum"]
    assert ex.tax.kind == "inter" and ex.tax.igst == Decimal("17748.00")
    assert ex.tax.rates_pct == [Decimal("18")]
    assert [ln.quantity for ln in ex.line_items] == [Decimal("2000"), Decimal("300")]
    assert [ln.tax_rate_pct for ln in ex.line_items] == [Decimal("18"), Decimal("18")]
    assert ex.doc_kind is DocKind.digital and ex.currency == "INR"
    assert ex.meta.provider == "fake" and ex.meta.prompt_id == "extract_invoice"
    assert ex.amount_in_words.value == Decimal("116348.00")


def test_s04_scanned_without_ocr_is_unavailable_but_high(world: Path, client: CountingFake) -> None:
    data, doc = _doc(world, "S04")
    assert doc.doc_kind is DocKind.scanned
    ex = extract(data, doc, client).extraction
    for name in (
        "invoice_number",
        "invoice_date",
        "supplier_gstin",
        "total",
        "bank_account_number",
    ):
        fv = getattr(ex, name)
        assert fv.grounded == "unavailable", name
        assert fv.level is ConfidenceLevel.high, name
    assert ex.po_reference.value is None and ex.po_reference.level is ConfidenceLevel.low
    assert ex.total.value == Decimal("43306.00")
    assert [ln.uom for ln in ex.line_items] == ["Coil", "Nos"]


def test_s08_tax_inclusive_taxable(world: Path, client: CountingFake) -> None:
    data, doc = _doc(world, "S08")
    ex = extract(data, doc, client).extraction
    assert ex.prices_include_tax is True
    (line,) = ex.line_items
    assert line.amount == Decimal("100000.00")
    assert line.tax_rate_pct == Decimal("18")
    assert line.taxable_amount == Decimal("84745.76")
    assert ex.tax.kind == "intra"
    assert ex.tax.cgst == ex.tax.sgst == Decimal("7627.12")
    assert "arithmetic" in ex.total.validators


def test_every_generated_document_normalises_to_truth(world: Path, client: CountingFake) -> None:
    for path in sorted((world / "truth").glob("[SH]*.json")):
        truth = json.loads(path.read_text(encoding="utf-8"))
        ev = truth["expected_values"]
        data, doc = _doc(world, path.stem)
        ex = extract(data, doc, client).extraction
        assert ex.total.value == Decimal(ev["total"]), path.stem
        assert ex.tax.total_tax == Decimal(ev["total_tax"]), path.stem
        assert ex.tax.kind == ev["tax_kind"], path.stem
        assert [ln.taxable_amount for ln in ex.line_items] == [
            Decimal(ln["taxable_amount"]) for ln in ev["lines"]
        ], path.stem
        assert str(ex.invoice_date.value) == ev["invoice_date"], path.stem
        assert ex.supplier_gstin.value == ev["supplier_gstin"], path.stem
        assert "arithmetic" in ex.total.validators, path.stem


def test_cache_hit_and_force_fresh(world: Path, client: CountingFake) -> None:
    data, doc = _doc(world, "S02")
    first = extract(data, doc, client)
    assert client.calls == 1 and first.extraction.meta.cached is False
    second = extract(data, doc, client)
    assert client.calls == 1
    assert second.extraction.meta.cached is True
    assert second.extraction.meta.cached_at is not None
    assert second.detail["cached"] is True
    assert "saved reading" in second.events[0].message
    third = extract(data, doc, client, force_fresh=True)
    assert client.calls == 2 and third.extraction.meta.cached is False


def test_cache_disabled(world: Path, client: CountingFake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CACHE", "0")
    get_settings.cache_clear()
    data, doc = _doc(world, "S03")
    extract(data, doc, client)
    extract(data, doc, client)
    assert client.calls == 2


def test_budget_limits_live_calls_but_not_cache(world: Path) -> None:
    db.init_db()
    live = CountingFake(world / "truth", live=True)
    budget = CallBudget(limit_per_hour=1)
    data, doc = _doc(world, "S06")
    extract(data, doc, live, budget=budget)
    extract(data, doc, live, budget=budget)  # cache hit: no budget used
    assert live.calls == 1
    with pytest.raises(BudgetExceededError):
        extract(data, doc, live, force_fresh=True, budget=budget)


def test_budget_window_expires() -> None:
    t = [0.0]
    budget = CallBudget(2, now=lambda: t[0])
    budget.acquire()
    budget.acquire()
    assert budget.remaining() == 0
    with pytest.raises(BudgetExceededError):
        budget.acquire()
    t[0] = 3600.0
    assert budget.remaining() == 2
    budget.acquire()


def test_events_carry_call_metadata(world: Path, client: CountingFake) -> None:
    data, doc = _doc(world, "S07")
    result = extract(data, doc, client)
    call = result.events[0].data["llm_call"]
    assert call["provider"] == "fake" and call["prompt"] == "extract_invoice@v1"
    assert {"latency_ms", "tokens_in", "tokens_out", "cached", "model"} <= call.keys()
    assert result.detail["fields_total"] >= result.detail["fields_grounded"] > 10


def test_unknown_document_raises(world: Path, client: CountingFake) -> None:
    import pymupdf

    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Some other invoice")
    data = pdf.tobytes()
    with pytest.raises(FakeProviderError):
        extract(data, read_bytes(data), client)
