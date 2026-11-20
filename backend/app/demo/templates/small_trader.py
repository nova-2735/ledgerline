"""Small-trader bill: typewriter face, simple ruled table, 'Rs.' totals with '/-'."""

from __future__ import annotations

import io

from reportlab.lib.colors import HexColor

from app.demo.invoice import Caps, PrintedInvoice

from .base import (
    GREY,
    PAGE_H,
    PAGE_W,
    Col,
    Pen,
    TableStyle,
    Template,
    draw_table,
    finish,
    new_canvas,
)
from .common import tax_label

CAPS = Caps(item_code=False, line_tax_rate=False)
M = 36
X0, X1 = M, PAGE_W - M
W = X1 - X0
F, FB, FI = "Courier", "Courier-Bold", "Courier-Oblique"
INK = HexColor("#1B2A6B")


def render(p: PrintedInvoice) -> bytes:
    buf = io.BytesIO()
    c = new_canvas(buf, p)
    pen = Pen(c)
    cx = PAGE_W / 2

    y = PAGE_H - 44
    pen.text(cx, y, p.title, FB, 10, "center")
    y -= 24
    pen.text(cx, y, p.supplier_name.upper(), FB, 17, "center")
    if p.tagline:
        y -= 14
        pen.text(cx, y, p.tagline, F, 8.5, "center")
    y -= 13
    pen.text(cx, y, p.supplier_address, F, 8.5, "center")
    y -= 12
    pen.text(cx, y, f"GSTIN: {p.supplier_gstin}   Ph: {p.supplier_phone}", F, 8.5, "center")
    y -= 12
    pen.text(cx, y, f"Email: {p.supplier_email}", F, 8.5, "center")
    y -= 10
    pen.hline(X0, X1, y, 1.2)
    pen.hline(X0, X1, y - 2.5, 0.5)

    y -= 22
    if p.number:
        pen.text(X0, y, f"Bill No.: {p.number}", FB, 10)
    pen.text(X1, y, f"Date: {p.date}", FB, 10, "right")
    if p.po_ref:
        y -= 14
        pen.text(X0, y, f"{p.po_label}: {p.po_ref}", F, 9.5)
    y -= 22
    pen.text(X0, y, "To,", F, 9.5)
    y -= 13
    pen.text(X0, y, f"M/s. {p.buyer_name}", FB, 10)
    for line in p.buyer_address_lines:
        y -= 12
        pen.text(X0 + 30, y, line, F, 9)
    y -= 12
    pen.text(X0 + 30, y, f"GSTIN: {p.buyer_gstin}", F, 9)
    y -= 12
    pen.text(X0 + 30, y, f"Place of Supply: {p.place_of_supply}", F, 9)

    y -= 18
    cols = [
        Col("S.No", 34, "center"),
        Col("Particulars", 0),
        Col("HSN", 46, "center"),
        Col("Qty", 70, "right"),
        Col("Rate", 72, "right"),
        Col("Amount", 86, "right"),
    ]
    fixed = sum(col.width for col in cols)
    cols = [Col(col.title, W - fixed, col.align) if col.width == 0 else col for col in cols]
    rows = [
        [
            ln.sl,
            ln.description,
            ln.hsn_sac,
            f"{ln.quantity} {ln.uom}" if ln.uom else ln.quantity,
            ln.unit_price,
            ln.amount,
        ]
        for ln in p.lines
    ]
    y = draw_table(
        pen,
        X0,
        y,
        cols,
        rows,
        TableStyle(font=F, size=9, header_font=FB, header_size=9, pad_y=6, min_rows_height=170),
    )

    lx, vx = X1 - 220, X1 - 4
    rows_t: list[tuple[str, str]] = []
    if p.subtotal:
        rows_t.append(("Sub Total", p.subtotal))
    rows_t += [(tax_label(t), t.amount) for t in p.taxes]
    if p.round_off:
        rows_t.append(("Round Off", p.round_off))
    ty = y - 16
    for label, value in rows_t:
        pen.text(lx, ty, label, F, 9.5)
        pen.text(vx, ty, value, F, 9.5, "right")
        ty -= 14
    pen.hline(lx, X1, ty + 9)
    pen.text(lx, ty - 5, "TOTAL", FB, 11)
    pen.text(vx, ty - 5, p.total, FB, 11, "right")
    pen.hline(lx, X1, ty - 11)
    pen.hline(lx, X1, ty - 13)

    wy = y - 16
    pen.text(X0, wy, "Amount in words:", F, 8.5)
    pen.para(X0, wy - 12, p.amount_in_words, lx - X0 - 20, FB, 8.5, 11)
    y = ty - 40

    for note in p.notes:
        pen.text(X0, y, note, FI, 9)
        y -= 13
    pen.text(X0, y, f"Bank: {p.bank_name}", F, 8.5)
    pen.text(X0, y - 12, f"A/c No.: {p.bank_account}   IFSC: {p.bank_ifsc}", F, 8.5)
    pen.text(X0, y - 24, f"A/c Name: {p.bank_account_name}", F, 8.5)
    pen.text(X0, y - 50, "E. & O.E.", F, 8)
    pen.text(X0, y - 62, "Goods once sold will not be taken back.", F, 8, color=GREY)

    pen.text(X1, y, f"For {p.supplier_name}", FB, 9.5, "right")
    # handwritten-style signature: oblique face, slight rotation, ink colour
    sig = p.supplier_name.split()[0]
    c.saveState()
    c.translate(X1 - 90, y - 34)
    c.rotate(7)
    pen.text(0, 0, sig, FI, 15, color=INK)
    c.restoreState()
    pen.text(X1, y - 52, "Proprietor / Authorised Signatory", F, 8, "right")
    return finish(c, buf)


TEMPLATE = Template("small_trader", CAPS, render)
