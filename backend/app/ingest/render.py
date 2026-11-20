"""Page renders (PNG) for the document viewer, cached under DATA_DIR/renders/<sha256>/."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pymupdf

from app.config import get_settings

from .storage import upload_path

MIN_SCALE, MAX_SCALE = 0.25, 4.0
_SHA = re.compile(r"^[0-9a-f]{64}$")


def render_path(sha256: str, page: int, scale: float) -> Path:
    return get_settings().data_dir / "renders" / sha256 / f"{page}@{scale:g}.png"


def _render(source: Path, page: int, scale: float, target: Path) -> None:
    with pymupdf.open(source) as doc:
        if not 0 <= page < doc.page_count:
            raise IndexError(f"page {page} out of range (document has {doc.page_count})")
        pix = doc[page].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    pix.save(str(tmp), output="png")
    os.replace(tmp, target)


def render_page_png(sha256: str, page: int, scale: float = 1.5) -> Path:
    """Path to a PNG of one page of a stored document; rendered on first request."""
    if not _SHA.match(sha256):
        raise ValueError("invalid document hash")
    if not MIN_SCALE <= scale <= MAX_SCALE:
        raise ValueError(f"scale must be between {MIN_SCALE} and {MAX_SCALE}")
    target = render_path(sha256, page, scale)
    if target.is_file():
        return target
    source = upload_path(sha256)
    if not source.is_file():
        raise FileNotFoundError(f"no stored document {sha256}")
    _render(source, page, scale, target)
    return target
