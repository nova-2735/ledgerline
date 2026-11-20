"""Optional OCR for scanned pages via Tesseract. Degrades to 'not available' when it's missing."""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image

from app.config import OCRMode, get_settings
from app.models.extraction import BBox, Word

OCR_DPI = 300
MIN_CONF = 0.3
_WINDOWS_PATHS = (
    Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
    Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
)


class OCRUnavailableError(RuntimeError):
    """OCR_ENABLED=1 but no Tesseract binary was found."""


@lru_cache
def tesseract_path() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    for path in _WINDOWS_PATHS:
        if path.is_file():
            return str(path)
    return None


def ocr_available() -> bool:
    """True when OCR would run for a scanned page under the current settings."""
    if get_settings().ocr_enabled is OCRMode.off:
        return False
    return tesseract_path() is not None


def should_ocr() -> bool:
    mode = get_settings().ocr_enabled
    if mode is OCRMode.off:
        return False
    if tesseract_path() is None:
        if mode is OCRMode.on:
            raise OCRUnavailableError("OCR_ENABLED=1 but Tesseract is not installed")
        return False
    return True


def ocr_page(page: pymupdf.Page, index: int) -> list[Word]:
    """Words with normalised boxes (0–1, top-left origin) and confidence 0–1."""
    cmd = tesseract_path()
    if cmd is None:
        raise OCRUnavailableError("Tesseract is not installed")
    pytesseract.pytesseract.tesseract_cmd = cmd
    pix = page.get_pixmap(dpi=OCR_DPI, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    w, h = float(pix.width), float(pix.height)
    words: list[Word] = []
    for text, conf, left, top, width, height in zip(
        data["text"],
        data["conf"],
        data["left"],
        data["top"],
        data["width"],
        data["height"],
        strict=True,
    ):
        text = str(text).strip()
        score = float(conf) / 100
        if not text or score < MIN_CONF:
            continue
        bbox = BBox(
            page=index,
            x0=max(0.0, left / w),
            y0=max(0.0, top / h),
            x1=min(1.0, (left + width) / w),
            y1=min(1.0, (top + height) / h),
        )
        words.append(Word(text=text, bbox=bbox, conf=round(score, 4)))
    return words
