"""CPU and setup costs kept off the run path: no OCR on digital pages, OCR at the scan's own
resolution, one PDF open per read, a shared and pre-warmed model client, cheap commits."""

from __future__ import annotations

import io
from typing import Any

import pymupdf
import pytest
from PIL import Image

from app import db
from app.config import Settings
from app.ingest import ocr as ocr_mod
from app.ingest import reader
from app.llm import base as llm_base
from app.llm.fake import FakeClient
from app.llm.gemini import GeminiClient


def _digital_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "TAX INVOICE  Invoice No: SPI/26-27/0214  Total 1,16,348.00")
    data = doc.tobytes()
    doc.close()
    return data


def _scan_pdf(image_dpi: int, pages: int = 1) -> bytes:
    """A page covered by one image rendered at `image_dpi` (A4)."""
    w, h = round(8.27 * image_dpi), round(11.69 * image_dpi)
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buf.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def test_digital_pages_are_never_ocrd(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any) -> list[Any]:
        raise AssertionError("OCR ran on a digital page")

    monkeypatch.setattr(reader, "ocr_page", boom)
    doc = reader.read_bytes(_digital_pdf(), ocr=True)
    assert doc.pages[0].kind.value == "digital" and not doc.pages[0].ocr_used


@pytest.mark.parametrize(("image_dpi", "expected"), [(150, 150), (170, 170), (72, 150), (600, 300)])
def test_ocr_rasterises_at_the_scans_own_resolution(image_dpi: int, expected: int) -> None:
    with pymupdf.open(stream=_scan_pdf(image_dpi), filetype="pdf") as doc:
        assert ocr_mod.ocr_dpi(doc[0]) == expected


def test_reading_opens_the_pdf_once(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[int] = []
    real_open = reader._open

    def counting(data: bytes) -> pymupdf.Document:
        opened.append(len(data))
        return real_open(data)

    monkeypatch.setattr(reader, "_open", counting)
    reader.read_bytes(_digital_pdf(), ocr=False)
    assert len(opened) == 1


def test_reading_still_refuses_bad_files() -> None:
    with pytest.raises(reader.IntakeError) as exc:
        reader.read_bytes(b"not a pdf at all", ocr=False)
    assert exc.value.code == "not_pdf"


def _gemini(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "app_env": "development",
        "llm_provider": "gemini",
        "llm_model": "gemini-test-main",
        "llm_model_light": "gemini-test-light",
        "gemini_api_key": "test-key",
    }
    return Settings(**(base | kw))


def test_live_client_is_shared_until_its_settings_change() -> None:
    first = llm_base.get_client(_gemini())
    assert isinstance(first, GeminiClient)
    assert llm_base.get_client(_gemini()) is first
    other = llm_base.get_client(_gemini(llm_model="gemini-test-other"))
    assert other is not first and other.model == "gemini-test-other"


def test_offline_clients_are_not_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _gemini(llm_provider="fake")
    assert isinstance(llm_base.get_client(settings), FakeClient)
    assert llm_base.get_client(settings) is not llm_base.get_client(settings)
    assert llm_base.warm_client(settings) is None


def test_warm_builds_the_sdk_client_without_a_call() -> None:
    client = llm_base.get_client(_gemini(llm_model="gemini-test-warm"))
    assert isinstance(client, GeminiClient) and client._sdk is None
    took = llm_base.warm_client(_gemini(llm_model="gemini-test-warm"))
    assert took is not None and client._sdk is not None


def test_warm_failures_are_swallowed() -> None:
    assert llm_base.warm_client(_gemini(llm_model="gemini-test-nokey", gemini_api_key=None)) is None


def test_sqlite_commits_skip_the_per_commit_fsync() -> None:
    db.init_db()
    with db.get_engine().connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 1  # NORMAL
