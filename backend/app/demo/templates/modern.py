"""Modern SaaS-style invoice: coloured header band, right-aligned meta, light rules, totals box."""

from __future__ import annotations

import io

from reportlab.lib.colors import Color, HexColor, white

from app.demo.invoice import Caps, PrintedInvoice

from .base import (
    GREY,
    PAGE_H,
    PAGE_W,
    RULE,
    Col,
    Pen,
    TableStyle,
    Template,
    draw_table,
    finish,
    hex_color,
    new_canvas,
)
from .common import tax_label

CAPS = Caps(item_code=True, line_tax_rate=True)
M = 40
X0, X1 = M, PAGE_W - M
W = X1 - X0
BOLD = "Helvetica-Bold"


def tint(color: Color, f: float) -> Color:
    return Color(1 - (1 - color.red) * f, 1 - (1 - color.green) * f, 1 - (1 - color.blue) * f)


def render(p: PrintedInvoice) -> bytes:
    buf = io.BytesIO()
    c = new_canvas(buf, p)
    pen = Pen(c)
    accent = hex_color(p.accent, "#0E6E6E")
    soft = tint(accent, 0.10)

    # header band
    band_h = 104
    pen.box(0, PAGE_H, PAGE_W, band_h, stroke=None, fill=accent)
    y = PAGE_H - 38
    pen.text(X0, y, p.supplier_name, BOLD, 16, color=white)
    y -= 16
    for line in p.supplier_address_lines:
        pen.text(X0, y, line, size=8.5, color=white)
        y -= 11
    pen.text(X0, y - 2, f"GSTIN {p.supplier_gstin}   ·   PAN {p.supplier_pan}", size=8, color=white)
    pen.text(X1, PAGE_H - 44, p.title, BOLD, 19, "right", white)
    if p.number:
        pen.text(X1, PAGE_H - 62, p.number, "Helvetica", 10, "right", white)

    # billed to | meta
    y = PAGE_H - band_h - 30
    pen.text(X0, y, "BILLED TO", BOLD, 7.5, color=accent)
    by = y - 15
    pen.text(X0, by, p.buyer_name, BOLD, 10.5)
    by -= 13
    for line in p.buyer_address_lines:
        pen.text(X0, by, line, size=8.5, color=GREY)
        by -= 11
    by -= 3
    pen.text(X0, by, f"GSTIN {p.buyer_gstin}", size=8.5, color=GREY)
    meta: list[tuple[str, str]] = []
    if p.number:
        meta.append(("Invoice No.", p.number))
    meta.append(("Invoice Date", p.date))
    if p.po_ref:
        meta.append((p.po_label, p.po_ref))
    meta.append(("Place of Supply", p.place_of_supply))
    my = y
    for label, value in meta:
        pen.text(X1 - 150, my, f"{label}:", size=8.5, color=GREY)
        pen.text(X1, my, value, BOLD, 8.5, "right")
        my -= 15
    y = min(by, my) - 22

    # items
    has_code = any(ln.item_code for ln in p.lines)
    has_uom = any(ln.uom for ln in p.lines)
    cols = [Col("#", 18, "left")]
    if has_code:
        cols.append(Col("Item", 70))
    cols.append(Col("Description", 0))
    cols += [Col("HSN/SAC", 46, "left"), Col("Qty", 30, "right")]
    if has_uom:
        cols.append(Col("Unit", 30, "left"))
    cols += [Col("Rate", 60, "right"), Col("GST", 30, "right"), Col("Amount", 68, "right")]
    fixed = sum(col.width for col in cols)
    cols = [Col(col.title, W - fixed, col.align) if col.width == 0 else col for col in cols]
    rows = []
    for ln in p.lines:
        row = (
            [ln.sl]
            + ([ln.item_code or ""] if has_code else [])
            + [ln.description, ln.hsn_sac, ln.quantity]
        )
        row += [ln.uom or ""] if has_uom else []
        row += [ln.unit_price, ln.tax_rate or "", ln.amount]
        rows.append(row)
    y = draw_table(
        pen,
        X0,
        y,
        cols,
        rows,
        TableStyle(
            size=8.8,
            header_size=7.5,
            pad_x=5,
            pad_y=7,
            grid="rows",
            rule=RULE,
            header_fill=soft,
            header_color=accent,
        ),
    )

    for note in p.notes:
        y -= 14
        pen.text(X0, y, note, "Helvetica-Oblique", 8.5, color=GREY)

    # notice box
    if p.notices:
        y -= 18
        amber_bg, amber = HexColor("#FFF6E0"), HexColor("#B7791F")
        lines = [ln for n in p.notices for ln in pen.wrap(n, BOLD, 9, W - 70)]
        h = 20 + 12 * len(lines)
        pen.box(X0, y, W, h, stroke=amber, fill=amber_bg, width=0.8, radius=3)
        pen.text(X0 + 12, y - 15, "IMPORTANT", BOLD, 7.5, color=amber)
        ly = y - 15
        for line in lines:
            pen.text(X0 + 70, ly, line, BOLD, 9, color=HexColor("#5C3D00"))
            ly -= 12
        y -= h

    # totals box
    y -= 20
    box_w = 220
    bx = X1 - box_w
    rows_t: list[tuple[str, str]] = []
    if p.subtotal:
        rows_t.append(("Subtotal", p.subtotal))
    rows_t += [(tax_label(t), t.amount) for t in p.taxes]
    if p.round_off:
        rows_t.append(("Round off", p.round_off))
    box_h = 14 + 16 * len(rows_t) + 30
    pen.box(bx, y, box_w, box_h, stroke=None, fill=soft, radius=4)
    ty = y - 18
    for label, value in rows_t:
        pen.text(bx + 12, ty, label, size=9, color=GREY)
        pen.text(X1 - 12, ty, value, size=9, align="right")
        ty -= 16
    pen.box(bx, ty + 4, box_w, 30, stroke=None, fill=accent, radius=4)
    pen.text(bx + 12, ty - 15, "Total", BOLD, 10.5, color=white)
    pen.text(X1 - 12, ty - 15, p.total, BOLD, 11.5, "right", white)

    pen.text(X0, y - 18, "Amount in words", BOLD, 7.5, color=accent)
    wy = pen.para(X0, y - 32, p.amount_in_words, bx - X0 - 24, "Helvetica", 9, 12)
    y = min(y - box_h, wy) - 26

    # payment details
    pen.text(X0, y, "PAYMENT DETAILS", BOLD, 7.5, color=accent)
    y -= 15
    for label, value in (
        ("Account name", p.bank_account_name),
        ("Bank", p.bank_name),
        ("Account no.", p.bank_account),
        ("IFSC", p.bank_ifsc),
    ):
        pen.text(X0, y, label, size=8.5, color=GREY)
        pen.text(X0 + 80, y, value, BOLD, 8.5)
        y -= 13
    if p.payment_terms_days:
        pen.text(
            X1,
            y + 13 * 4,
            f"Payment due within {p.payment_terms_days} days",
            size=8.5,
            align="right",
            color=GREY,
        )

    # footer
    pen.hline(X0, X1, 62, 0.6, RULE)
    pen.text(X0, 48, f"{p.supplier_phone}   ·   {p.supplier_email}", size=8, color=GREY)
    pen.text(X1, 48, "Thank you for your business.", "Helvetica-Oblique", 8, "right", GREY)
    pen.text(
        X0,
        35,
        "This is a computer-generated invoice and does not require a physical signature.",
        size=7,
        color=GREY,
    )
    return finish(c, buf)


TEMPLATE = Template("modern", CAPS, render)
