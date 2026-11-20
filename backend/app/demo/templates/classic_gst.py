"""Classic bordered GST tax invoice: centred title, meta block, ruled item grid, HSN tax summary."""

from __future__ import annotations

import io

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
from .common import hsn_summary_rows, tax_label

CAPS = Caps(item_code=True, line_tax_rate=False)
M = 30
X0, X1 = M, PAGE_W - M
W = X1 - X0
BOLD = "Helvetica-Bold"


def _kv(pen: Pen, x: float, y: float, label: str, value: str, label_w: float) -> None:
    pen.text(x, y, label, "Helvetica", 8.5, color=GREY)
    pen.text(x + label_w, y, value, BOLD, 8.5)


def render(p: PrintedInvoice) -> bytes:
    buf = io.BytesIO()
    c = new_canvas(buf, p)
    pen = Pen(c)
    top = PAGE_H - M
    mark = p.currency_mark

    # title strip
    y = top
    pen.text(PAGE_W / 2, y - 17, p.title, BOLD, 13, "center")
    pen.text(X1 - 8, y - 15, "(ORIGINAL FOR RECIPIENT)", "Helvetica", 6.5, "right", GREY)
    y -= 25
    pen.hline(X0, X1, y)

    # supplier | invoice details
    split = X0 + 292
    sec_top = y
    sy = y - 18
    pen.text(X0 + 8, sy, p.supplier_name, BOLD, 12.5)
    sy -= 15
    for line in p.supplier_address_lines:
        pen.text(X0 + 8, sy, line, size=8.5)
        sy -= 11.5
    sy -= 2
    for label, value in (
        ("GSTIN/UIN", p.supplier_gstin),
        ("State", p.supplier_state),
        ("Phone", p.supplier_phone),
        ("E-mail", p.supplier_email),
    ):
        _kv(pen, X0 + 8, sy, f"{label}:", value, 52)
        sy -= 11.5
    meta: list[tuple[str, str]] = []
    if p.number:
        meta.append(("Invoice No.:", p.number))
    meta.append(("Invoice Date:", p.date))
    if p.po_ref:
        meta.append((f"{p.po_label}:", p.po_ref))
    meta += [("Place of Supply:", p.place_of_supply), ("Reverse Charge:", "No")]
    if p.payment_terms_days:
        meta.append(("Payment Terms:", f"{p.payment_terms_days} days"))
    my = y - 18
    for label, value in meta:
        _kv(pen, split + 10, my, label, value, 82)
        my -= 15
    y = min(sy, my) - 6
    pen.vline(split, sec_top, y)
    pen.hline(X0, X1, y)

    # buyer | dispatch
    sec_top = y
    by = y - 13
    pen.text(X0 + 8, by, "Buyer (Bill to)", "Helvetica", 7.5, color=GREY)
    by -= 13
    pen.text(X0 + 8, by, p.buyer_name, BOLD, 10)
    by -= 12.5
    for line in p.buyer_address_lines:
        pen.text(X0 + 8, by, line, size=8.5)
        by -= 11.5
    by -= 2
    _kv(pen, X0 + 8, by, "GSTIN/UIN:", p.buyer_gstin, 52)
    by -= 11.5
    _kv(pen, X0 + 8, by, "State:", p.buyer_state, 52)
    dy = y - 13
    pen.text(split + 10, dy, "Consignee (Ship to)", "Helvetica", 7.5, color=GREY)
    dy -= 13
    pen.text(split + 10, dy, "Stores, Peenya Plant", BOLD, 9)
    dy -= 12.5
    pen.text(split + 10, dy, "Kestrel Foods Pvt. Ltd., Bengaluru", size=8.5)
    dy -= 16
    _kv(pen, split + 10, dy, "Dispatched through:", "Road transport", 82)
    dy -= 13
    _kv(pen, split + 10, dy, "Terms of Delivery:", "Door delivery", 82)
    y = min(by, dy) - 9
    pen.vline(split, sec_top, y)

    # items
    has_code = any(ln.item_code for ln in p.lines)
    code_w = 66 if has_code else 0
    cols = [Col("Sl", 22, "center")]
    if has_code:
        cols.append(Col("Item Code", code_w))
    cols += [
        Col("Description of Goods", 251 - code_w),
        Col("HSN/SAC", 46, "center"),
        Col("Qty", 42, "right"),
        Col("Unit", 36, "center"),
        Col("Rate", 58, "right"),
        Col(f"Amount ({mark})", 0, "right"),
    ]
    used = sum(col.width for col in cols)
    cols[-1] = Col(cols[-1].title, W - used, "right")
    rows = [
        [ln.sl]
        + ([ln.item_code or ""] if has_code else [])
        + [ln.description, ln.hsn_sac, ln.quantity, ln.uom or "", ln.unit_price, ln.amount]
        for ln in p.lines
    ]
    y = draw_table(
        pen,
        X0,
        y,
        cols,
        rows,
        TableStyle(size=8.5, header_size=8, min_rows_height=185, header_fill=None),
    )

    # remarks + totals
    if p.notes:
        ny = y - 13
        for note in p.notes:
            pen.text(X0 + 8, ny, f"Remarks: {note}", "Helvetica-Oblique", 8.5)
            ny -= 12
        y = ny + 3
        pen.hline(X0, X1, y)
    tot_x = X0 + W - 210
    rows_t: list[tuple[str, str]] = []
    if p.subtotal:
        rows_t.append(("Taxable Value", p.subtotal))
    rows_t += [(tax_label(t), t.amount) for t in p.taxes]
    if p.round_off:
        rows_t.append(("Round Off", p.round_off))
    ty = y - 14
    for label, value in rows_t:
        pen.text(tot_x + 8, ty, label, size=8.5)
        pen.text(X1 - 6, ty, value, size=8.5, align="right")
        ty -= 13
    ty -= 2
    pen.hline(tot_x, X1, ty + 9)
    pen.text(tot_x + 8, ty - 4, "Grand Total", BOLD, 10)
    pen.text(X1 - 6, ty - 4, p.total, BOLD, 10.5, "right")
    ty -= 13
    pen.vline(tot_x, y, ty)
    wy = y - 14
    pen.text(X0 + 8, wy, "Amount Chargeable (in words)", "Helvetica", 7.5, color=GREY)
    wy = pen.para(X0 + 8, wy - 12, p.amount_in_words, tot_x - X0 - 16, BOLD, 9, 11.5)
    y = min(ty, wy) - 2
    pen.hline(X0, X1, y)

    # HSN-wise tax summary
    y -= 8
    cols_h, rows_h = hsn_summary_rows(p)
    y = draw_table(
        pen,
        X0 + 8,
        y,
        [Col(t, w, a) for t, w, a in cols_h],
        rows_h,
        TableStyle(size=7.5, header_size=7, pad_y=3.5, rule_width=0.4),
    )
    y -= 8
    pen.hline(X0, X1, y)

    # bank | signatory
    sec_top = y
    bx = X0 + 8
    by = y - 13
    pen.text(bx, by, "Company's Bank Details", BOLD, 8.5)
    by -= 13
    for label, value in (
        ("A/c Holder's Name:", p.bank_account_name),
        ("Bank Name:", p.bank_name),
        ("A/c No.:", p.bank_account),
        ("IFS Code:", p.bank_ifsc),
    ):
        _kv(pen, bx, by, label, value, 82)
        by -= 12
    pen.text(X1 - 10, y - 13, f"for {p.supplier_name}", BOLD, 9, "right")
    pen.text(X1 - 10, by + 4, "Authorised Signatory", "Helvetica", 8, "right")
    y = by - 4
    pen.vline(split, sec_top, y)
    pen.hline(X0, X1, y)

    # declaration
    dy = y - 12
    pen.text(X0 + 8, dy, "Declaration", BOLD, 7.5)
    pen.para(
        X0 + 8,
        dy - 10,
        "We declare that this invoice shows the actual price of the goods described and that all "
        "particulars are true and correct.",
        W - 16,
        "Helvetica",
        7.5,
        9.5,
        GREY,
    )
    y = dy - 26
    c.setLineWidth(0.8)
    c.rect(X0, y, W, top - y)
    city = p.supplier_address_lines[1].split(",")[0]
    pen.text(
        PAGE_W / 2,
        y - 12,
        f"SUBJECT TO {city.upper()} JURISDICTION",
        "Helvetica",
        7,
        "center",
        GREY,
    )
    return finish(c, buf)


TEMPLATE = Template("classic_gst", CAPS, render)
