"""Find transcribed values on the page (text layer or OCR words) to get highlight boxes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import cached_property
from typing import Literal

from rapidfuzz import fuzz

from app.models.extraction import BBox, DocumentRead, Word

from .normalize import parse_amount, parse_date

Grounded = Literal["exact", "fuzzy", "none", "unavailable"]
FUZZY_MIN = 90


@dataclass(frozen=True)
class GroundResult:
    status: Grounded
    bbox: list[BBox] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.status in ("exact", "fuzzy")


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def union_bbox(words: list[Word]) -> list[BBox]:
    """One box per page covering the matched words."""
    by_page: dict[int, list[BBox]] = {}
    for w in words:
        by_page.setdefault(w.bbox.page, []).append(w.bbox)
    return [
        BBox(
            page=page,
            x0=min(b.x0 for b in boxes),
            y0=min(b.y0 for b in boxes),
            x1=max(b.x1 for b in boxes),
            y1=max(b.y1 for b in boxes),
        )
        for page, boxes in sorted(by_page.items())
    ]


class Grounder:
    """Searches windows of adjacent words (within a page) for a value."""

    def __init__(self, doc: DocumentRead) -> None:
        self.pages = [p.words for p in doc.pages]
        self.available = any(self.pages)

    def _windows(self, size: int) -> list[tuple[str, list[Word]]]:
        out = []
        for words in self.pages:
            for i in range(len(words) - size + 1):
                chunk = words[i : i + size]
                out.append((" ".join(w.text for w in chunk), chunk))
        return out

    @cached_property
    def _amounts(self) -> list[tuple[Decimal, list[Word]]]:
        found = []
        for size in (1, 2, 3):
            for text, chunk in self._windows(size):
                value = parse_amount(text)
                if value is not None:
                    found.append((value, chunk))
        return found

    @cached_property
    def _dates(self) -> list[tuple[date, list[Word]]]:
        found = []
        for size in (1, 2, 3):
            for text, chunk in self._windows(size):
                parsed = parse_date(text)
                if parsed is not None:
                    found.append((parsed.value, chunk))
        return found

    def _unavailable(self) -> GroundResult | None:
        return None if self.available else GroundResult("unavailable")

    def number(self, value: Decimal | None) -> GroundResult:
        if (miss := self._unavailable()) is not None:
            return miss
        if value is None:
            return GroundResult("none")
        for found, chunk in self._amounts:
            if found == value:
                return GroundResult("exact", union_bbox(chunk))
        return GroundResult("none")

    def date(self, value: date | None) -> GroundResult:
        if (miss := self._unavailable()) is not None:
            return miss
        if value is None:
            return GroundResult("none")
        for found, chunk in self._dates:
            if found == value:
                return GroundResult("exact", union_bbox(chunk))
        return GroundResult("none")

    def text(self, value: str | None) -> GroundResult:
        if (miss := self._unavailable()) is not None:
            return miss
        target = _norm(value or "")
        if not target:
            return GroundResult("none")
        n = len((value or "").split())
        sizes = range(max(1, n - 2), n + 3)
        candidates = [(t, c) for size in sizes for t, c in self._windows(size)]
        for text, chunk in candidates:
            if _norm(text) == target:
                return GroundResult("exact", union_bbox(chunk))
        best: tuple[float, list[Word]] | None = None
        for text, chunk in candidates:
            score = fuzz.ratio(_norm(text), target)
            if score >= FUZZY_MIN and (best is None or score > best[0]):
                best = (score, chunk)
        if best is not None:
            return GroundResult("fuzzy", union_bbox(best[1]))
        return GroundResult("none")
