"""Shared drawing helpers for invoice templates (reportlab canvas, invariant output)."""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.config import get_settings
from app.demo.invoice import RUPEE_SIGN, Caps, PrintedInvoice

PAGE_W, PAGE_H = A4
SYMBOL_FONT = "InvoiceSymbol"
GREY = HexColor("#555555")
LIGHT = HexColor("#9A9A9A")
RULE = HexColor("#C8C8C8")

_DEJAVU_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    Path("/Library/Fonts/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/DejaVuSans.ttf"),
)


def _has_rupee(path: Path) -> bool:
    try:
        font = TTFont("probe", str(path))
    except Exception:
        return False
    return ord(RUPEE_SIGN) in font.face.charToGlyph


@lru_cache
def _symbol_font_path(configured: str | None) -> Path | None:
    candidates = [Path(configured)] if configured else []
    candidates += list(_DEJAVU_CANDIDATES)
    for path in candidates:
        if path.is_file() and _has_rupee(path):
            return path
    return None


def rupee_font() -> Path | None:
    """Font file used for the ₹ glyph, or None (then invoices print 'Rs.')."""
    configured = get_settings().invoice_font_path
    path = _symbol_font_path(str(configured) if configured else None)
    if path is not None and SYMBOL_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(SYMBOL_FONT, str(path)))
    return path


def rupee_available() -> bool:
    return rupee_font() is not None


def hex_color(value: str | None, default: str) -> Color:
    return HexColor(value or default)


class Pen:
    """Canvas wrapper: text with ₹ drawn in the symbol font, wrapping, rules and boxes."""

    def __init__(self, canvas: Canvas) -> None:
        self.c = canvas

    def _runs(self, text: str, font: str) -> list[tuple[str, str]]:
        if RUPEE_SIGN not in text:
            return [(text, font)]
        runs: list[tuple[str, str]] = []
        for i, part in enumerate(text.split(RUPEE_SIGN)):
            if i:
                runs.append((RUPEE_SIGN, SYMBOL_FONT))
            if part:
                runs.append((part, font))
        return runs

    def width(self, text: str, font: str, size: float) -> float:
        return sum(pdfmetrics.stringWidth(t, f, size) for t, f in self._runs(text, font))

    def text(
        self,
        x: float,
        y: float,
        text: str,
        font: str = "Helvetica",
        size: float = 9,
        align: str = "left",
        color: Color = black,
    ) -> None:
        w = self.width(text, font, size)
        if align == "right":
            x -= w
        elif align == "center":
            x -= w / 2
        self.c.setFillColor(color)
        for part, f in self._runs(text, font):
            self.c.setFont(f, size)
            self.c.drawString(x, y, part)
            x += pdfmetrics.stringWidth(part, f, size)

    def wrap(self, text: str, font: str, size: float, width: float) -> list[str]:
        return simpleSplit(text, font, size, width) or [""]

    def para(
        self,
        x: float,
        y: float,
        text: str,
        width: float,
        font: str = "Helvetica",
        size: float = 9,
        leading: float | None = None,
        color: Color = black,
        align: str = "left",
    ) -> float:
        """Draw wrapped text from baseline y; returns the baseline after the last line."""
        lead = leading or size * 1.3
        ax = x + width if align == "right" else x + width / 2 if align == "center" else x
        for line in self.wrap(text, font, size, width):
            self.text(ax, y, line, font, size, align, color)
            y -= lead
        return y

    def hline(
        self, x1: float, x2: float, y: float, width: float = 0.5, color: Color = black
    ) -> None:
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width)
        self.c.line(x1, y, x2, y)

    def vline(
        self, x: float, y1: float, y2: float, width: float = 0.5, color: Color = black
    ) -> None:
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width)
        self.c.line(x, y1, x, y2)

    def box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        stroke: Color | None = black,
        fill: Color | None = None,
        width: float = 0.5,
        radius: float = 0,
    ) -> None:
        """Rectangle with its top-left corner at (x, y)."""
        self.c.setLineWidth(width)
        if stroke is not None:
            self.c.setStrokeColor(stroke)
        if fill is not None:
            self.c.setFillColor(fill)
        draw = self.c.roundRect if radius else self.c.rect
        args = (x, y - h, w, h, radius) if radius else (x, y - h, w, h)
        draw(*args, stroke=int(stroke is not None), fill=int(fill is not None))  # type: ignore[operator]


@dataclass(frozen=True)
class Col:
    title: str
    width: float
    align: str = "left"


@dataclass(frozen=True)
class TableStyle:
    font: str = "Helvetica"
    size: float = 8.5
    header_font: str = "Helvetica-Bold"
    header_size: float = 8
    pad_x: float = 4
    pad_y: float = 4.5
    grid: str = "full"  # full | rows | none
    rule: Color = black
    rule_width: float = 0.5
    header_fill: Color | None = None
    header_color: Color = black
    min_rows_height: float = 0  # pad the body to at least this height (blank invoice space)


def draw_table(
    pen: Pen,
    x: float,
    top: float,
    cols: Sequence[Col],
    rows: Sequence[Sequence[str]],
    style: TableStyle,
    sub_rows: Sequence[Sequence[str] | None] | None = None,
) -> float:
    """Draw a table with wrapping cells; returns the y of its bottom edge.

    `sub_rows` optionally adds a second, smaller grey line under a cell (e.g. an item code).
    """
    total_w = sum(c.width for c in cols)
    lead = style.size * 1.25
    edges = [x]
    for c in cols:
        edges.append(edges[-1] + c.width)

    # header
    header_lines = [
        pen.wrap(c.title, style.header_font, style.header_size, c.width - 2 * style.pad_x)
        for c in cols
    ]
    hh = max(len(h) for h in header_lines) * style.header_size * 1.2 + 2 * style.pad_y
    if style.header_fill is not None:
        pen.box(x, top, total_w, hh, stroke=None, fill=style.header_fill)
    for c, lines, x0, x1 in zip(cols, header_lines, edges, edges[1:], strict=False):
        y = top - style.pad_y - style.header_size
        for line in lines:
            tx = (
                x1 - style.pad_x
                if c.align == "right"
                else (x0 + x1) / 2
                if c.align == "center"
                else x0 + style.pad_x
            )
            pen.text(tx, y, line, style.header_font, style.header_size, c.align, style.header_color)
            y -= style.header_size * 1.2
    y = top - hh
    if style.grid != "none":
        pen.hline(x, x + total_w, top, style.rule_width, style.rule)
        pen.hline(x, x + total_w, y, style.rule_width, style.rule)

    body_top = y
    for r, row in enumerate(rows):
        wrapped = [
            pen.wrap(cell, style.font, style.size, c.width - 2 * style.pad_x)
            for c, cell in zip(cols, row, strict=True)
        ]
        sub = sub_rows[r] if sub_rows else None
        n = max(len(w) + (1 if sub and sub[i] else 0) for i, w in enumerate(wrapped))
        rh = n * lead + 2 * style.pad_y - (lead - style.size)
        for i, (c, lines, x0, x1) in enumerate(zip(cols, wrapped, edges, edges[1:], strict=False)):
            ty = y - style.pad_y - style.size
            tx = (
                x1 - style.pad_x
                if c.align == "right"
                else (x0 + x1) / 2
                if c.align == "center"
                else x0 + style.pad_x
            )
            for line in lines:
                pen.text(tx, ty, line, style.font, style.size, c.align)
                ty -= lead
            if sub and sub[i]:
                pen.text(tx, ty + 0.5, sub[i] or "", style.font, style.size - 1.5, c.align, GREY)
        y -= rh
        if style.grid == "rows":
            pen.hline(x, x + total_w, y, style.rule_width * 0.6, style.rule)
    if style.min_rows_height and body_top - y < style.min_rows_height:
        y = body_top - style.min_rows_height
    if style.grid == "full":
        pen.hline(x, x + total_w, y, style.rule_width, style.rule)
        for e in edges:
            pen.vline(e, top, y, style.rule_width, style.rule)
    return y


def new_canvas(buf: io.BytesIO, p: PrintedInvoice) -> Canvas:
    c = Canvas(buf, pagesize=A4, invariant=1, pageCompression=1)
    title = f"{p.title.title()} {p.number}" if p.number else p.title.title()
    c.setTitle(title)
    c.setAuthor(p.supplier_name)
    c.setSubject(f"{p.title.title()} to {p.buyer_name}")
    c.setCreator(p.supplier_name)
    return c


def finish(c: Canvas, buf: io.BytesIO) -> bytes:
    c.showPage()
    c.save()
    return buf.getvalue()


def monogram(name: str) -> str:
    skip = {"pvt.", "ltd.", "llp", "&", "and", "of"}
    letters = [
        w[0] for w in name.replace("&", " ").split() if w.lower() not in skip and w[0].isalpha()
    ]
    return "".join(letters[:3]).upper()


Renderer = Callable[[PrintedInvoice], bytes]


@dataclass(frozen=True)
class Template:
    name: str
    caps: Caps
    render: Renderer


__all__ = [
    "GREY",
    "LIGHT",
    "PAGE_H",
    "PAGE_W",
    "RULE",
    "Col",
    "Pen",
    "TableStyle",
    "Template",
    "black",
    "draw_table",
    "finish",
    "hex_color",
    "monogram",
    "new_canvas",
    "rupee_available",
    "white",
]
