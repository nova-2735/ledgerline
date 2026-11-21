"""Upload and abuse hardening: per-address rate limit, per-client share of live model readings,
clear refusals for files that can't be read."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import limits
from app.config import get_settings
from app.db import get_sessionmaker
from app.enums import StageName
from app.extract.extractor import transcribe
from app.llm.base import CallMeta, ClientBudgetExceededError, LLMClient
from app.llm.budget import CallBudget, ClientBudgets, client_budget
from app.llm.cache import LLMCache
from app.models.extraction import DocumentRead, RawInvoice
from app.orm import RunRow
from app.pipeline.runner import friendly_error


def _pdf(pages: int = 1, **save: Any) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Invoice page {i + 1}")
    data = doc.tobytes(**save)
    doc.close()
    return data


def _upload(api: TestClient, data: bytes, name: str = "invoice.pdf") -> Any:
    return api.post("/api/runs", files={"file": (name, data, "application/pdf")})


def _runs() -> int:
    with get_sessionmaker()() as s:
        return int(s.scalar(select(func.count()).select_from(RunRow)) or 0)


def _limit(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


# --- rate limit -------------------------------------------------------------------------------


def test_too_many_runs_from_one_address_get_a_friendly_429(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _limit(monkeypatch, RATE_LIMIT_RUNS_PER_MINUTE="2", RATE_LIMIT_BURST="2")
    assert api.post("/api/demo/runs/S01").status_code == 202
    assert api.post("/api/demo/runs/S02").status_code == 202
    blocked = api.post("/api/demo/runs/S03")
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "rate_limited" and "try again" in body["detail"]
    assert int(blocked.headers["Retry-After"]) >= 1
    # uploads share the same bucket
    assert _upload(api, _pdf()).status_code == 429


def test_token_bucket_refills_and_keeps_addresses_apart() -> None:
    now = [0.0]
    b = limits.TokenBuckets(now=lambda: now[0])
    assert b.take("a", per_minute=6, burst=2) == 0
    assert b.take("a", per_minute=6, burst=2) == 0
    wait = b.take("a", per_minute=6, burst=2)
    assert 9 < wait <= 10  # one token every 10 s
    assert b.take("b", per_minute=6, burst=2) == 0  # another address is unaffected
    now[0] += 10
    assert b.take("a", per_minute=6, burst=2) == 0


# --- model-reading budget ----------------------------------------------------------------------


def test_a_client_that_used_its_readings_is_refused_before_a_run_is_created(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _limit(monkeypatch, MAX_LIVE_LLM_CALLS_PER_CLIENT_PER_HOUR="1")
    monkeypatch.setattr(limits, "needs_live_reading", lambda *a, **k: True)
    client_budget(1).acquire("testclient")
    before = _runs()
    resp = _upload(api, _pdf())
    assert resp.status_code == 429
    assert resp.json()["code"] == "reading_limit" and "readings" in resp.json()["detail"]
    assert int(resp.headers["Retry-After"]) > 0
    assert _runs() == before
    # a file whose reading is saved needs no live call and still goes through
    monkeypatch.setattr(limits, "needs_live_reading", lambda *a, **k: False)
    assert _upload(api, _pdf()).status_code == 202


def test_the_global_budget_also_refuses_up_front(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _limit(monkeypatch, MAX_LIVE_LLM_CALLS_PER_HOUR="7")
    monkeypatch.setattr(limits, "needs_live_reading", lambda *a, **k: True)
    from app.llm.budget import get_budget

    budget = get_budget(7)
    while budget.remaining():
        budget.acquire()
    resp = api.post("/api/demo/runs/S01", json={"force_fresh": True})
    assert (resp.status_code, resp.json()["code"]) == (429, "reading_limit")


def test_client_budgets_count_per_address_within_the_hour() -> None:
    now = [0.0]
    b = ClientBudgets(2, now=lambda: now[0])
    b.acquire("a")
    b.acquire("a")
    with pytest.raises(ClientBudgetExceededError):
        b.acquire("a")
    assert b.remaining("b") == 2
    assert 3599 <= b.retry_after("a") <= 3600
    now[0] += 3600
    assert b.remaining("a") == 2


class _Live(LLMClient):
    provider, model, model_light, is_live = "stub", "stub-model", "stub-light", True

    def __init__(self) -> None:
        self.calls = 0

    def extract_invoice(self, pdf_bytes: bytes, doc: DocumentRead) -> tuple[RawInvoice, CallMeta]:
        self.calls += 1
        raw = RawInvoice.model_validate(_RAW)
        return raw, CallMeta(provider="stub", model="stub-model", prompt_id="extract_invoice",
                             prompt_version="v1", latency_ms=1)  # fmt: skip

    def map_lines(self, inv: Any, po: Any) -> Any:
        raise NotImplementedError

    def polish(self, summary: str, facts: Any) -> Any:
        raise NotImplementedError


_RAW: dict[str, Any] = {
    "document_type": "tax_invoice", "document_title": None, "invoice_number": "X-1",
    "invoice_date": None, "due_date": None, "supplier_name": "S", "supplier_gstin": None,
    "supplier_address": None, "supplier_phone": None, "supplier_email": None,
    "buyer_name": None, "buyer_gstin": None, "place_of_supply": None, "po_reference": None,
    "currency": None, "line_items": [], "subtotal": None, "tax_lines": [], "other_charges": [],
    "round_off": None, "total": "100.00", "amount_in_words": None, "prices_include_tax": None,
    "bank_account_name": None, "bank_account_number": None, "bank_ifsc": None,
    "bank_name": None, "annotations": [], "legibility": "clear",
}  # fmt: skip


def test_new_files_from_one_caller_cannot_drain_the_shared_budget(seeded_db: Path) -> None:
    """Every new file is a cache miss; past the caller's share the reading is refused while the
    shared budget is left for everyone else."""
    settings = get_settings().model_copy(update={"max_live_llm_calls_per_client_per_hour": 3})
    shared = CallBudget(100)
    client = _Live()
    for i in range(3):
        doc = DocumentRead(sha256=f"{i:064d}", pages=[], doc_kind="digital",
                           ocr_available=False, page_count=1)  # fmt: skip
        transcribe(b"%PDF", doc, client, settings=settings, cache=LLMCache(), budget=shared,
                   caller="10.0.0.9")  # fmt: skip
    doc = DocumentRead(sha256="9" * 64, pages=[], doc_kind="digital", ocr_available=False,
                       page_count=1)  # fmt: skip
    with pytest.raises(ClientBudgetExceededError):
        transcribe(b"%PDF", doc, client, settings=settings, cache=LLMCache(), budget=shared,
                   caller="10.0.0.9")  # fmt: skip
    assert client.calls == 3 and shared.remaining() == 97
    transcribe(b"%PDF", doc, client, settings=settings, cache=LLMCache(), budget=shared,
               caller="10.0.0.10")  # fmt: skip
    assert client.calls == 4
    message = friendly_error(StageName.extract_fields, ClientBudgetExceededError("x"))
    assert "this address" in message.lower()


# --- files that can't be read -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "status", "code", "phrase"),
    [
        (b"", 422, "not_pdf", "empty"),
        (b"PK\x03\x04 this is a zip, not a pdf", 422, "not_pdf", "isn't a PDF"),
        (_pdf(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u"), 422,
         "encrypted", "password-protected"),
        (_pdf(pages=11), 422, "too_many_pages", "11 pages; the limit is 10"),
        (b"%PDF-1.7\n" + b"0" * (10 * 1024 * 1024), 413, "too_large", "10 MB limit"),
    ],
)  # fmt: skip
def test_unreadable_uploads_get_clear_messages(
    api: TestClient, data: bytes, status: int, code: str, phrase: str
) -> None:
    before = _runs()
    resp = _upload(api, data)
    assert resp.status_code == status
    assert resp.json()["code"] == code and phrase in resp.json()["detail"]
    assert _runs() == before
