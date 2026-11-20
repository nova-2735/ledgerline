"""Intake validation and document reading: page kind, text and word boxes (OCR for scans).

Documents are opened from bytes and treated as data only: nothing embedded is executed, and at
most MAX_PAGES pages are ever loaded.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.config import get_settings
from app.enums import DocKind
from app.models.extraction import BBox, DocumentRead, PageRead, Word

from .ocr import ocr_available, ocr_page, should_ocr

SCANNED_TEXT_CHARS = 30
SCANNED_IMAGE_COVERAGE = 0.5
PDF_MAGIC = b"%PDF-"


class IntakeError(Exception):
    """A file that can't be accepted. `code` is one of: not_pdf, too_large, too_many_pages,
    encrypted, corrupt."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PdfInfo:
    sha256: str
    size_bytes: int
    page_count: int


def _open(data: bytes) -> pymupdf.Document:
    try:
        return pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise IntakeError("corrupt", "The PDF file is damaged and can't be opened.") from exc


def _check_bytes(data: bytes) -> None:
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise IntakeError("too_large", f"The file is larger than {settings.max_upload_mb} MB.")
    if PDF_MAGIC not in data[:1024]:
        raise IntakeError("not_pdf", "The file is not a PDF.")


def _check_document(doc: pymupdf.Document) -> int:
    """Page count of an opened PDF that passes the intake checks."""
    max_pages = get_settings().max_pages
    if doc.needs_pass or doc.is_encrypted or doc.metadata.get("encryption"):
        raise IntakeError("encrypted", "The PDF is password-protected or encrypted.")
    if doc.page_count < 1:
        raise IntakeError("corrupt", "The PDF has no pages.")
    if doc.page_count > max_pages:
        raise IntakeError("too_many_pages", f"The PDF has more than {max_pages} pages.")
    return int(doc.page_count)


def validate_pdf(data: bytes) -> PdfInfo:
    """Check upload limits and that the bytes are a readable, unencrypted PDF."""
    _check_bytes(data)
    with _open(data) as doc:
        pages = _check_document(doc)
    return PdfInfo(hashlib.sha256(data).hexdigest(), len(data), pages)


def _clamp(v: float) -> float:
    return min(1.0, max(0.0, v))


def _image_coverage(page: pymupdf.Page) -> float:
    area = page.rect.width * page.rect.height
    if area <= 0:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        if not r.is_empty:
            covered += r.width * r.height
    return min(1.0, covered / area)


def _digital_words(page: pymupdf.Page, index: int) -> list[Word]:
    w, h = page.rect.width, page.rect.height
    words = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words", sort=True):
        bbox = BBox(
            page=index, x0=_clamp(x0 / w), y0=_clamp(y0 / h), x1=_clamp(x1 / w), y1=_clamp(y1 / h)
        )
        words.append(Word(text=text, bbox=bbox, conf=None))
    return words


def _read_page(page: pymupdf.Page, index: int, use_ocr: bool) -> PageRead:
    text = page.get_text("text")
    scanned = (
        len(text.strip()) < SCANNED_TEXT_CHARS and _image_coverage(page) > SCANNED_IMAGE_COVERAGE
    )
    words: list[Word] = []
    ocr_used = False
    mean_conf: float | None = None
    if scanned:
        if use_ocr:
            words = ocr_page(page, index)
            ocr_used = True
            confs = [wd.conf for wd in words if wd.conf is not None]
            mean_conf = round(sum(confs) / len(confs), 4) if confs else None
            text = " ".join(wd.text for wd in words)
    else:
        words = _digital_words(page, index)
    return PageRead(
        index=index,
        width_pt=page.rect.width,
        height_pt=page.rect.height,
        kind=DocKind.scanned if scanned else DocKind.digital,
        text=text,
        words=words,
        ocr_used=ocr_used,
        ocr_mean_conf=mean_conf,
    )


def read_bytes(data: bytes, ocr: bool | None = None) -> DocumentRead:
    """Read a PDF already in memory (opened once: checks, text, words and OCR). `ocr` overrides
    OCR_ENABLED (None = use settings)."""
    _check_bytes(data)
    use_ocr = should_ocr() if ocr is None else ocr
    with _open(data) as doc:
        count = _check_document(doc)
        pages = [_read_page(doc[i], i, use_ocr) for i in range(count)]
    kinds = {p.kind for p in pages}
    doc_kind = kinds.pop() if len(kinds) == 1 else DocKind.mixed
    return DocumentRead(
        sha256=hashlib.sha256(data).hexdigest(),
        pages=pages,
        doc_kind=doc_kind,
        ocr_available=ocr_available(),
        page_count=count,
    )


def read_document(path: Path, ocr: bool | None = None) -> DocumentRead:
    return read_bytes(Path(path).read_bytes(), ocr=ocr)
