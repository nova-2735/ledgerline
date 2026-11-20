from __future__ import annotations

import io
import os
import time
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from app import db
from app.config import get_settings
from app.demo.generate import render_document
from app.demo.invoice import load_specs, load_world
from app.enums import DocKind
from app.ingest import render as render_mod
from app.ingest.ocr import tesseract_path
from app.ingest.reader import IntakeError, read_bytes, read_document, validate_pdf
from app.ingest.render import render_page_png
from app.ingest.storage import store_document, upload_path


@pytest.fixture(scope="module")
def pdfs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    out = tmp_path_factory.mktemp("docs")
    world = load_world()
    paths = {}
    for spec in load_specs(world):
        if spec.id in {"S01", "S04"}:
            pdf, _ = render_document(spec, world, rupee_ok=False)
            paths[spec.id] = out / f"{spec.id}.pdf"
            paths[spec.id].write_bytes(pdf)
    return paths


def _pdf(pages: int = 1, **save: object) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Page {i + 1} of a test document")
    data = doc.tobytes(**save)
    doc.close()
    return data


# --- reading --------------------------------------------------------------------------------------


def test_digital_invoice_words_and_boxes(pdfs: dict[str, Path]) -> None:
    doc = read_document(pdfs["S01"])
    assert doc.doc_kind is DocKind.digital
    assert doc.page_count == 1 and len(doc.pages) == 1
    page = doc.pages[0]
    assert page.kind is DocKind.digital and not page.ocr_used
    matches = [w for w in page.words if w.text == "SPI/26-27/0214"]
    assert matches
    for w in page.words:
        b = w.bbox
        assert 0 <= b.x0 <= b.x1 <= 1 and 0 <= b.y0 <= b.y1 <= 1
        assert w.conf is None
    # top-left origin: the title sits near the top of the page
    title = next(w for w in page.words if w.text == "TAX")
    assert title.bbox.y0 < 0.1
    assert len(doc.sha256) == 64


def test_digital_read_is_fast(pdfs: dict[str, Path]) -> None:
    read_document(pdfs["S01"])
    start = time.perf_counter()
    read_document(pdfs["S01"])
    assert time.perf_counter() - start < 0.3


def test_scanned_invoice_without_ocr(pdfs: dict[str, Path]) -> None:
    assert get_settings().ocr_enabled.value == "0"  # APP_ENV=test forces OCR off
    doc = read_document(pdfs["S04"])
    assert doc.doc_kind is DocKind.scanned
    page = doc.pages[0]
    assert page.kind is DocKind.scanned
    assert page.words == []
    assert page.ocr_used is False
    assert doc.ocr_available is False


def test_mixed_document_kind(pdfs: dict[str, Path]) -> None:
    merged = pymupdf.open()
    for key in ("S01", "S04"):
        with pymupdf.open(pdfs[key]) as part:
            merged.insert_pdf(part)
    data = merged.tobytes()
    merged.close()
    doc = read_bytes(data)
    assert [p.kind for p in doc.pages] == [DocKind.digital, DocKind.scanned]
    assert doc.doc_kind is DocKind.mixed


@pytest.mark.ocr
def test_scanned_invoice_with_ocr(pdfs: dict[str, Path]) -> None:
    if tesseract_path() is None:
        pytest.skip("tesseract not installed")
    doc = read_document(pdfs["S04"], ocr=True)
    page = doc.pages[0]
    assert page.ocr_used is True
    assert len(page.words) >= 40
    assert any("RSE" in w.text or "Rao" in w.text.title() for w in page.words)
    assert page.ocr_mean_conf is not None and 0 < page.ocr_mean_conf <= 1
    for w in page.words:
        assert w.conf is not None and w.conf >= 0.3
        assert 0 <= w.bbox.x0 <= w.bbox.x1 <= 1 and 0 <= w.bbox.y0 <= w.bbox.y1 <= 1


# --- intake limits -------------------------------------------------------------------------------


def _code(data: bytes) -> str:
    with pytest.raises(IntakeError) as err:
        validate_pdf(data)
    return err.value.code


def test_rejects_encrypted_pdf() -> None:
    data = _pdf(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    assert _code(data) == "encrypted"


def test_rejects_owner_password_only_pdf() -> None:
    data = _pdf(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="")
    assert _code(data) == "encrypted"


def test_rejects_too_many_pages() -> None:
    assert _code(_pdf(pages=11)) == "too_many_pages"
    assert validate_pdf(_pdf(pages=10)).page_count == 10


def test_rejects_random_bytes() -> None:
    assert _code(os.urandom(4096)) == "not_pdf"


def test_rejects_corrupt_pdf() -> None:
    assert _code(b"%PDF-1.7\n" + b"\x00garbage" * 50) == "corrupt"


def test_rejects_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    assert _code(b"%PDF-1.7\n" + b"0" * (1024 * 1024)) == "too_large"


# --- storage and renders -------------------------------------------------------------------------


def test_store_document_dedupes(pdfs: dict[str, Path]) -> None:
    db.init_db()
    data = pdfs["S01"].read_bytes()
    first = store_document(data, "C:\\fakepath\\S01.pdf")
    second = store_document(data, "copy.pdf")
    assert first.created is True and second.created is False
    assert first.id == second.id
    assert first.filename == "S01.pdf"
    assert upload_path(first.sha256).read_bytes() == data
    with pytest.raises(IntakeError):
        store_document(b"not a pdf", "x.pdf")


def test_render_png_aspect_and_cache(
    pdfs: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    db.init_db()
    stored = store_document(pdfs["S01"].read_bytes(), "S01.pdf")
    path = render_page_png(stored.sha256, 0, 1.5)
    assert path.name == "0@1.5.png"
    with Image.open(io.BytesIO(path.read_bytes())) as img:
        assert img.format == "PNG"
        ratio = img.width / img.height
    with pymupdf.open(stored.path) as doc:
        page_ratio = doc[0].rect.width / doc[0].rect.height
    assert abs(ratio - page_ratio) / page_ratio < 0.01

    def boom(*_: object) -> None:
        raise AssertionError("render should have come from the cache")

    monkeypatch.setattr(render_mod, "_render", boom)
    assert render_page_png(stored.sha256, 0, 1.5) == path


def test_render_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        render_page_png("../../etc", 0, 1.0)
    with pytest.raises(ValueError):
        render_page_png("a" * 64, 0, 10)
    with pytest.raises(FileNotFoundError):
        render_page_png("a" * 64, 0, 1.0)
