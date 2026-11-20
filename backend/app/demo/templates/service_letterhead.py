"""Service-company letterhead invoice: monogram, narrative lines with SAC, payment terms footer."""

from __future__ import annotations

import io

from reportlab.lib.colors import white

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
    monogram,
    new_canvas,
)
from .common import tax_label
from .modern import tint

CAPS = Caps(item_code=False, line_tax_rate=False)
M = 44
X0, X1 = M, PAGE_W - M
W = X1 - X0
BOLD = "Helvetica-Bold"


def render(p: PrintedInvoice) -> bytes:
    buf = io.BytesIO()
    c = new_canvas(buf, p)
    pen = Pen(c)
    accent = hex_color(p.accent, "#1F4E79")

    # letterhead
    top = PAGE_H - 46
    r = 25
    c.setFillColor(accent)
    c.circle(X0 + r, top - r + 6, r, stroke=0, fill=1)
    pen.text(X0 + r, top - r + 1, monogram(p.supplier_name), BOLD, 15, "center", white)
    tx = X0 + 2 * r + 14
    pen.text(tx, top - 8, p.supplier_name, BOLD, 15, color=accent)
    if p.tagline:
        pen.text(tx, top - 22, p.tagline, "Helvetica-Oblique", 8.5, color=GREY)
    pen.text(tx, top - 35, p.supplier_address, size=8, color=GREY)
    pen.text(
        tx,
        top - 47,
        f"GSTIN: {p.supplier_gstin}   |   Phone: {p.supplier_phone}   |   {p.supplier_email}",
        size=8,
        color=GREY,
    )
    y = top - 60
    pen.hline(X0, X1, y, 2.2, accent)
    pen.hline(X0, X1, y - 3.5, 0.5, accent)

    # title + meta
    y -= 32
    pen.text(X0, y, p.title, BOLD, 14, color=accent)
    y -= 26
    pen.text(X0, y, "To", BOLD, 8, color=accent)
    by = y - 14
    pen.text(X0, by, p.buyer_name, BOLD, 10)
    by -= 12.5
    for line in p.buyer_address_lines:
        pen.text(X0, by, line, size=8.5)
        by -= 11.5
    by -= 2
    pen.text(X0, by, f"GSTIN: {p.buyer_gstin}", size=8.5)
    meta: list[tuple[str, str]] = []
    if p.number:
        meta.append(("Invoice No.", p.number))
    meta.append(("Date", p.date))
    if p.po_ref:
        meta.append((p.po_label, p.po_ref))
    meta.append(("Place of Supply", p.place_of_supply))
    mx = X0 + W * 0.58
    my = y
    for label, value in meta:
        pen.text(mx, my, f"{label}:", size=8.5, color=GREY)
        pen.text(mx + 88, my, value, BOLD, 8.5)
        my -= 15
    y = min(by, my) - 24

    # narrative lines
    has_uom = any(ln.uom for ln in p.lines)
    cols = [
        Col("Sl.", 24, "left"),
        Col("Description of Service", 0),
        Col("SAC", 50),
        Col("Qty", 34, "right"),
    ]
    if has_uom:
        cols.append(Col("Unit", 62))
    cols += [Col("Rate", 70, "right"), Col("Amount", 78, "right")]
    fixed = sum(col.width for col in cols)
    cols = [Col(col.title, W - fixed, col.align) if col.width == 0 else col for col in cols]
    rows = [
        [ln.sl, ln.description, ln.hsn_sac, ln.quantity]
        + ([ln.uom or ""] if has_uom else [])
        + [ln.unit_price, ln.amount]
        for ln in p.lines
    ]
    y = draw_table(
        pen,
        X0,
        y,
        cols,
        rows,
        TableStyle(
            size=9,
            header_size=8,
            pad_x=5,
            pad_y=7,
            grid="rows",
            rule=RULE,
            header_fill=tint(accent, 0.12),
            header_color=accent,
            min_rows_height=60,
        ),
    )
    pen.hline(X0, X1, y, 0.5, RULE)
    for note in p.notes:
        y -= 14
        pen.text(X0 + 5, y, f"Note: {note}", "Helvetica-Oblique", 8.5, color=GREY)

    # totals
    y -= 22
    lx, vx = X1 - 230, X1 - 5
    rows_t: list[tuple[str, str]] = []
    if p.subtotal:
        rows_t.append(("Taxable Value", p.subtotal))
    if not p.prices_include_tax:
        rows_t += [(tax_label(t), t.amount) for t in p.taxes]
    if p.round_off:
        rows_t.append(("Round Off", p.round_off))
    ty = y
    for label, value in rows_t:
        pen.text(lx, ty, label, size=9)
        pen.text(vx, ty, value, size=9, align="right")
        ty -= 15
    pen.hline(lx - 5, X1, ty + 9, 0.6, accent)
    total_label = "Total (inclusive of GST)" if p.prices_include_tax else "Total"
    pen.text(lx, ty - 5, total_label, BOLD, 10)
    pen.text(vx, ty - 5, p.total, BOLD, 10.5, "right")
    ty -= 14
    pen.hline(lx - 5, X1, ty, 0.6, accent)
    if p.inclusive_note:
        ty -= 13
        pen.text(vx, ty, p.inclusive_note, size=8, align="right", color=GREY)
    pen.text(X0, y, "Amount in words", size=8, color=GREY)
    wy = pen.para(X0, y - 13, p.amount_in_words, lx - X0 - 30, BOLD, 9, 12)
    y = min(ty, wy) - 26

    # terms + bank + signature
    pen.text(X0, y, "Payment terms", BOLD, 8.5, color=accent)
    days = p.payment_terms_days or 15
    pen.text(X0, y - 13, f"Payment due within {days} days from the date of invoice.", size=8.5)
    y -= 34
    pen.text(X0, y, "Bank details for remittance", BOLD, 8.5, color=accent)
    y -= 13
    for label, value in (
        ("Account Name", p.bank_account_name),
        ("Bank", p.bank_name),
        ("Account No.", p.bank_account),
        ("IFSC", p.bank_ifsc),
    ):
        pen.text(X0, y, f"{label}:", size=8.5, color=GREY)
        pen.text(X0 + 78, y, value, size=8.5)
        y -= 12
    pen.text(X1, y + 12 * 5, f"For {p.supplier_name}", BOLD, 9, "right")
    pen.text(X1, y + 6, "Authorised Signatory", size=8.5, align="right")

    # footer bar
    pen.box(0, 34, PAGE_W, 34, stroke=None, fill=accent)
    pen.text(
        PAGE_W / 2,
        14,
        f"{p.supplier_name}  ·  {p.supplier_address}",
        size=7.5,
        align="center",
        color=white,
    )
    return finish(c, buf)


TEMPLATE = Template("service_letterhead", CAPS, render)
