"""Optional OCR for scanned pages via Tesseract. Degrades to 'not available' when it's missing."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image

from app.config import OCRMode, get_settings
from app.models.extraction import BBox, Word

# Rasterise a scan at its own resolution, kept between these bounds: upsampling a 150 dpi scan
# to 300 dpi costs about twice the OCR time and finds no more words.
MIN_OCR_DPI, MAX_OCR_DPI = 150, 300
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


def ocr_dpi(page: pymupdf.Page) -> int:
    """The resolution of the page's largest image, clamped to [MIN_OCR_DPI, MAX_OCR_DPI]."""
    best = 0.0
    for info in page.get_image_info():
        width_pt = info["bbox"][2] - info["bbox"][0]
        if width_pt > 0 and info.get("width"):
            best = max(best, info["width"] / width_pt * 72)
    return int(min(MAX_OCR_DPI, max(MIN_OCR_DPI, round(best))))


# A scanned page is checked for sideways or upside-down text when it is landscape or its first
# OCR pass is weak; Tesseract's orientation detection (OSD) then says how to turn it.
WEAK_MEAN_CONF = 0.70
MIN_OSD_CONF = 1.5


@dataclass(frozen=True)
class _Box:
    text: str
    conf: float
    x0: float  # normalised to the OCR'd image
    y0: float
    x1: float
    y1: float


def _read(img: Image.Image) -> list[_Box]:
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    w, h = float(img.width), float(img.height)
    out = []
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
        if text and score >= MIN_CONF:
            out.append(_Box(text, score, left / w, top / h, (left + width) / w, (top + height) / h))
    return out


def _quality(boxes: list[_Box]) -> float:
    return sum(b.conf for b in boxes)


def _mean(boxes: list[_Box]) -> float:
    return _quality(boxes) / len(boxes) if boxes else 0.0


def upright_angle(img: Image.Image) -> int:
    """Counter-clockwise degrees (0, 90, 180, 270) that turn the page upright, per OSD; 0 when
    OSD is unsure or unavailable."""
    try:
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
    except (pytesseract.TesseractError, ValueError):
        return 0
    if float(osd.get("orientation_conf", 0)) < MIN_OSD_CONF:
        return 0
    return (360 - int(osd.get("rotate", 0))) % 360  # OSD's "rotate" is clockwise


def _unrotate(b: _Box, angle: int) -> tuple[float, float, float, float]:
    """Box from the image turned `angle` degrees counter-clockwise back to the page's frame."""
    corners = [(b.x0, b.y0), (b.x1, b.y1)]
    if angle == 90:
        pts = [(1 - y, x) for x, y in corners]
    elif angle == 180:
        pts = [(1 - x, 1 - y) for x, y in corners]
    elif angle == 270:
        pts = [(y, 1 - x) for x, y in corners]
    else:
        pts = corners
    xs, ys = [x for x, _ in pts], [y for _, y in pts]
    return min(xs), min(ys), max(xs), max(ys)


def ocr_page(page: pymupdf.Page, index: int) -> list[Word]:
    """Words with normalised boxes (0–1, top-left origin, in the page's own frame) and
    confidence 0–1. A sideways or upside-down scan is turned upright before reading."""
    cmd = tesseract_path()
    if cmd is None:
        raise OCRUnavailableError("Tesseract is not installed")
    pytesseract.pytesseract.tesseract_cmd = cmd
    # Greyscale: a third of the pixels to encode and hand over, about a third less OCR time.
    pix = page.get_pixmap(dpi=ocr_dpi(page), alpha=False, colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    boxes, angle = _read(img), 0
    if img.width > img.height or _mean(boxes) < WEAK_MEAN_CONF:
        turn = upright_angle(img)
        if turn:
            turned = _read(img.rotate(turn, expand=True))
            if _quality(turned) > _quality(boxes):
                boxes, angle = turned, turn
    words: list[Word] = []
    for b in boxes:
        x0, y0, x1, y1 = _unrotate(b, angle)
        bbox = BBox(
            page=index,
            x0=max(0.0, x0),
            y0=max(0.0, y0),
            x1=min(1.0, x1),
            y1=min(1.0, y1),
        )
        words.append(Word(text=b.text, bbox=bbox, conf=round(b.conf, 4)))
    return words
