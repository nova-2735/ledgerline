"""Out-of-distribution stress documents U01–U10 for the robustness pack (docs/ROBUSTNESS.md).

Layouts are drawn here, independently of the four scenario templates: a two-page invoice, a
sideways scan, a phone photo, an unregistered trader's bill, a US-style invoice in USD, a credit
note, an e-invoice with IRN and QR block, a discount-and-TCS invoice, two invoices in one file
and a delivery challan. Each document's ground truth is the `RawInvoice` a careful reader would
return, built from the same strings the PDF prints, plus the expected outcome.

python -m app.demo.unseen --out data/demo   (also run by `generate`)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymupdf
from num2words import num2words
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter
from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.config import get_settings
from app.models.extraction import RawInvoice, RawLine, RawTaxLine

from .money import amount_in_words, format_indian, format_western, q2, round_off

FOLDER = "unseen"
SEED = 42
STRESS_PREFIX = "U"


# --- printed content ------------------------------------------------------------------------------


@dataclass
class Party:
    name: str
    address: list[str]
    gstin: str | None = None
    phone: str | None = None
    email: str | None = None


@dataclass
class Item:
    description: str
    qty: Decimal | None
    uom: str | None
    rate: Decimal | None
    amount: Decimal
    hsn: str | None = None
    code: str | None = None


@dataclass
class Tax:
    kind: str  # CGST / SGST / IGST / OTHER
    rate: Decimal | None
    amount: Decimal
    label: str | None = None  # printed label for OTHER, e.g. "TCS u/s 206C(1H)"


@dataclass
class Bill:
    """Everything printed on one invoice-like document, as strings where it matters."""

    doc_type: str
    title: str | None
    number: str | None
    date: str | None
    supplier: Party
    buyer: Party
    items: list[Item]
    taxes: list[Tax] = field(default_factory=list)
    fmt: Callable[[Decimal], str] = format_indian
    mark: str = "Rs."
    currency: str | None = "INR"
    due_date: str | None = None
    po_label: str | None = None
    po_ref: str | None = None
    place_of_supply: str | None = None
    round_off: Decimal = Decimal("0.00")
    words: str | None = None
    bank: dict[str, str] = field(default_factory=dict)
    annotations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    legibility: str = "clear"
    show_subtotal: bool = True
    priced: bool = True  # False for a delivery challan: quantities only

    @property
    def subtotal(self) -> Decimal:
        return q2(sum((i.amount for i in self.items), Decimal()))

    @property
    def total(self) -> Decimal:
        return q2(self.subtotal + sum((t.amount for t in self.taxes), Decimal()) + self.round_off)

    def money(self, v: Decimal) -> str:
        return self.fmt(v)

    def total_text(self) -> str:
        return f"{self.mark} {self.money(self.total)}".strip()


def _rate(v: Decimal | None) -> str | None:
    return None if v is None else f"{v.normalize():f}%"


def _qty(v: Decimal | None) -> str | None:
    return None if v is None else f"{v.normalize():f}"


def raw_from(bill: Bill) -> dict[str, Any]:
    """The ground-truth RawInvoice for a bill (strings exactly as printed)."""
    raw = RawInvoice(
        document_type=bill.doc_type,  # type: ignore[arg-type]
        document_title=bill.title,
        invoice_number=bill.number if bill.priced else None,  # a challan number is not one
        invoice_date=bill.date,
        due_date=bill.due_date,
        supplier_name=bill.supplier.name,
        supplier_gstin=bill.supplier.gstin,
        supplier_address=", ".join(bill.supplier.address),
        supplier_phone=bill.supplier.phone,
        supplier_email=bill.supplier.email,
        buyer_name=bill.buyer.name,
        buyer_gstin=bill.buyer.gstin,
        place_of_supply=bill.place_of_supply,
        po_reference=bill.po_ref,
        currency=bill.currency,
        line_items=[
            RawLine(
                description=i.description,
                item_code=i.code,
                hsn_sac=i.hsn,
                quantity=_qty(i.qty),
                uom=i.uom,
                unit_price=bill.money(i.rate) if i.rate is not None else None,
                amount=bill.money(i.amount) if bill.priced else None,
                tax_rate=None,
            )
            for i in bill.items
        ],
        subtotal=bill.money(bill.subtotal) if bill.show_subtotal and bill.priced else None,
        tax_lines=[
            RawTaxLine(tax_type=t.kind, rate=_rate(t.rate), amount=bill.money(t.amount))  # type: ignore[arg-type]
            for t in bill.taxes
        ],
        other_charges=[],
        round_off=(f"{'+' if bill.round_off >= 0 else '-'}{abs(bill.round_off):.2f}")
        if bill.round_off
        else None,
        total=bill.total_text() if bill.priced else None,
        amount_in_words=bill.words,
        prices_include_tax=False if bill.taxes else None,
        bank_account_name=bill.bank.get("holder"),
        bank_account_number=bill.bank.get("account"),
        bank_ifsc=bill.bank.get("ifsc"),
        bank_name=bill.bank.get("bank"),
        annotations=list(bill.annotations),
        legibility=bill.legibility,  # type: ignore[arg-type]
    )
    return raw.model_dump(mode="json")


# --- drawing --------------------------------------------------------------------------------------


class Pen:
    """A thin wrapper over a reportlab canvas with top-left coordinates in points."""

    def __init__(self, c: Canvas, size: tuple[float, float], font: str = "Helvetica") -> None:
        self.c, self.w, self.h, self.font = c, size[0], size[1], font

    def text(
        self,
        x: float,
        y: float,
        s: str,
        size: float = 9,
        bold: bool = False,
        align: str = "left",
        font: str | None = None,
    ) -> None:
        name = font or self.font
        if bold:
            name = {
                "Helvetica": "Helvetica-Bold",
                "Times-Roman": "Times-Bold",
                "Courier": "Courier-Bold",
            }.get(name, name)
        self.c.setFont(name, size)
        yy = self.h - y
        if align == "right":
            self.c.drawRightString(x, yy, s)
        elif align == "center":
            self.c.drawCentredString(x, yy, s)
        else:
            self.c.drawString(x, yy, s)

    def line(self, x0: float, y0: float, x1: float, y1: float, width: float = 0.6) -> None:
        self.c.setLineWidth(width)
        self.c.line(x0, self.h - y0, x1, self.h - y1)

    def rect(self, x: float, y: float, w: float, h: float, fill: float | None = None) -> None:
        if fill is not None:
            self.c.setFillGray(fill)
            self.c.rect(x, self.h - y - h, w, h, stroke=1, fill=1)
            self.c.setFillGray(0)
        else:
            self.c.rect(x, self.h - y - h, w, h, stroke=1, fill=0)


def _new_pdf(size: tuple[float, float], title: str) -> tuple[io.BytesIO, Canvas]:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=size, invariant=1, pageCompression=1)
    c.setTitle(title)
    c.setCreator("Ledgerline stress generator")
    return buf, c


def _party_block(
    p: Pen, x: float, y: float, label: str | None, party: Party, size: float = 8.5
) -> float:
    if label:
        p.text(x, y, label, size - 1, bold=True)
        y += 11
    p.text(x, y, party.name, size + 0.5, bold=True)
    y += 11
    for ln in party.address:
        p.text(x, y, ln, size)
        y += 10
    if party.gstin:
        p.text(x, y, f"GSTIN: {party.gstin}", size)
        y += 10
    if party.phone:
        p.text(x, y, f"Ph: {party.phone}", size)
        y += 10
    if party.email:
        p.text(x, y, party.email, size)
        y += 10
    return y


@dataclass(frozen=True)
class Columns:
    """Table columns: (header, x, align, getter)."""

    cols: Sequence[tuple[str, float, str, Callable[[int, Item], str]]]


def _item_columns(bill: Bill, x0: float, x1: float, hsn: bool = True) -> Columns:
    m = bill.money
    cols: list[tuple[str, float, str, Callable[[int, Item], str]]] = [
        ("#", x0 + 4, "left", lambda n, i: str(n)),
        ("Description", x0 + 24, "left", lambda n, i: i.description),
    ]
    if hsn:
        cols.append(("HSN/SAC", x1 - 230, "left", lambda n, i: i.hsn or ""))
    cols += [
        ("Qty", x1 - 160, "right", lambda n, i: _qty(i.qty) or ""),
        ("Unit", x1 - 155, "left", lambda n, i: i.uom or ""),
        ("Rate", x1 - 70, "right", lambda n, i: m(i.rate) if i.rate is not None else ""),
        ("Amount", x1 - 4, "right", lambda n, i: m(i.amount)),
    ]
    return Columns(cols)


def _table(
    p: Pen,
    y: float,
    x0: float,
    x1: float,
    cols: Columns,
    rows: list[tuple[int, Item]],
    grid: bool = True,
    size: float = 8.0,
    row_h: float = 15,
) -> float:
    p.rect(x0, y, x1 - x0, row_h, fill=0.9)
    for head, x, align, _ in cols.cols:
        p.text(x, y + 10.5, head, size, bold=True, align=align)
    y += row_h
    for n, item in rows:
        for _, x, align, get in cols.cols:
            p.text(x, y + 10.5, get(n, item), size, align=align)
        y += row_h
        if grid:
            p.line(x0, y, x1, y, 0.3)
    p.line(x0, y, x1, y, 0.8)
    return y


def _totals(
    p: Pen,
    bill: Bill,
    y: float,
    x_label: float,
    x_value: float,
    size: float = 8.5,
    extra: Sequence[tuple[str, str]] = (),
) -> float:
    m = bill.money
    rows: list[tuple[str, str, bool]] = []
    if bill.show_subtotal:
        rows.append(("Taxable Value" if bill.taxes else "Sub Total", m(bill.subtotal), False))
    for label, value in extra:
        rows.append((label, value, False))
    for t in bill.taxes:
        label = t.label or f"{t.kind} @ {_rate(t.rate)}"
        rows.append((label, m(t.amount), False))
    if bill.round_off:
        rows.append(
            ("Round Off", f"{'+' if bill.round_off >= 0 else '-'}{abs(bill.round_off):.2f}", False)
        )
    rows.append(("Grand Total", bill.total_text(), True))
    for label, value, bold in rows:
        p.text(x_label, y, label, size, bold=bold)
        p.text(x_value, y, value, size + (1 if bold else 0), bold=bold, align="right")
        y += 13
    return y


def _bank(p: Pen, bill: Bill, x: float, y: float, size: float = 8) -> float:
    if not bill.bank:
        return y
    p.text(x, y, "Bank details for payment", size, bold=True)
    y += 11
    for key, label in (
        ("holder", "A/c Name"),
        ("bank", "Bank"),
        ("account", "A/c No."),
        ("ifsc", "IFSC"),
        ("swift", "SWIFT"),
        ("routing", "ABA routing"),
    ):
        if key in bill.bank:
            p.text(x, y, f"{label}: {bill.bank[key]}", size)
            y += 10
    return y


# --- the ten documents ---------------------------------------------------------------------------

KESTREL = Party(
    "Kestrel Foods Pvt. Ltd.",
    ["Plot 14, 2nd Phase, Peenya Industrial Area", "Bengaluru, Karnataka 560058"],
    gstin="29AAJCK4417M1Z1",
)
KESTREL_NO_GSTIN = Party(KESTREL.name, KESTREL.address)


def _items(spec: Sequence[tuple[str, str, str, str, str]]) -> list[Item]:
    """(description, hsn, qty, uom, rate) → items with amount = qty × rate."""
    out = []
    for desc, hsn, qty, uom, rate in spec:
        q, r = Decimal(qty), Decimal(rate)
        out.append(Item(desc, q, uom, r, q2(q * r), hsn=hsn))
    return out


def _gst(subtotal: Decimal, rate: Decimal, intra: bool) -> list[Tax]:
    if intra:
        half = q2(subtotal * rate / 2 / 100)
        return [Tax("CGST", rate / 2, half), Tax("SGST", rate / 2, half)]
    return [Tax("IGST", rate, q2(subtotal * rate / 100))]


def _finish(bill: Bill, words: bool = True) -> Bill:
    """Round the total to the rupee and print the amount in words (INR bills)."""
    exact = q2(bill.subtotal + sum((t.amount for t in bill.taxes), Decimal()))
    _, delta = round_off(exact)
    bill.round_off = delta
    if words:
        bill.words = amount_in_words(bill.total)
    return bill


# U01 — two pages, 28 lines, totals on page 2 --------------------------------------------------

BHARAT = Party(
    "Bharat Office Supplies",
    ["No. 18, Avenue Road, Chickpet", "Bengaluru, Karnataka 560002"],
    gstin="29AQZPB7715N1ZX",
    phone="+91 80 2296 1122",
    email="sales@bharatoffice.example",
)
BHARAT_BANK = {
    "holder": "Bharat Office Supplies",
    "bank": "Canara Bank",
    "account": "0111201000456",
    "ifsc": "CNRB0000111",
}

U01_ITEMS = [
    ("Ball pen, blue, box of 50", "9608", "12", "Box", "275.00"),
    ("Ball pen, black, box of 50", "9608", "6", "Box", "275.00"),
    ("Gel pen 0.5 mm, assorted, box of 20", "9608", "8", "Box", "340.00"),
    ("Permanent marker, black, pack of 10", "9608", "10", "Pack", "180.00"),
    ("Whiteboard marker, assorted, pack of 4", "9608", "15", "Pack", "96.00"),
    ("Highlighter, fluorescent, pack of 5", "9608", "10", "Pack", "125.00"),
    ("Pencil HB with eraser, box of 10", "9609", "20", "Box", "60.00"),
    ("Eraser, dust-free, pack of 20", "4016", "5", "Pack", "110.00"),
    ("Sharpener, metal, pack of 20", "8214", "5", "Pack", "130.00"),
    ("Spiral notebook A5, 200 pages", "4820", "60", "Nos", "58.00"),
    ("Long notebook, 172 pages", "4820", "40", "Nos", "46.00"),
    ("Register, ruled, 400 pages", "4820", "12", "Nos", "185.00"),
    ("Sticky notes 3x3 in, pad of 100", "4820", "40", "Pad", "42.00"),
    ("Box file, laminated, foolscap", "4820", "30", "Nos", "95.00"),
    ("Lever arch file, 75 mm", "4820", "24", "Nos", "135.00"),
    ("Clear bag, A4, pack of 10", "3926", "20", "Pack", "88.00"),
    ("Document folder with button, A4", "3926", "50", "Nos", "18.00"),
    ("Stapler No. 10", "8472", "10", "Nos", "145.00"),
    ("Staple pins No. 10, box of 20 x 1000", "8305", "10", "Box", "120.00"),
    ("Paper clips 33 mm, box of 100", "8305", "25", "Box", "22.00"),
    ("Binder clips 25 mm, box of 12", "8305", "20", "Box", "48.00"),
    ("Punch machine, two-hole", "8472", "6", "Nos", "220.00"),
    ("Scissors 8 in, stainless steel", "8213", "10", "Nos", "75.00"),
    ("Glue stick 15 g", "3506", "40", "Nos", "28.00"),
    ("Cello tape 24 mm x 65 m", "3919", "40", "Roll", "34.00"),
    ("Calculator, 12-digit, desktop", "8470", "6", "Nos", "485.00"),
    ("Desk organiser, 4 compartments", "3926", "8", "Nos", "265.00"),
    ("Whiteboard duster, magnetic", "9603", "10", "Nos", "65.00"),
]


def u01() -> tuple[bytes, Bill]:
    bill = Bill(
        doc_type="tax_invoice",
        title="TAX INVOICE",
        number="BOS/2627/0602",
        date="18-11-2026",
        supplier=BHARAT,
        buyer=KESTREL,
        items=_items(U01_ITEMS),
        po_label="PO#",
        po_ref="0161",
        place_of_supply="29-Karnataka",
        bank=BHARAT_BANK,
    )
    bill.taxes = _gst(bill.subtotal, Decimal(18), intra=True)
    _finish(bill)
    buf, c = _new_pdf(A4, "Invoice BOS/2627/0602")
    rows = list(enumerate(bill.items, start=1))
    for page_no, chunk in ((1, rows[:20]), (2, rows[20:])):
        p = Pen(c, A4)
        p.text(40, 46, BHARAT.name.upper(), 15, bold=True)
        p.text(40, 60, "Stationery · Office consumables · Printing", 8)
        p.text(555, 46, bill.title or "", 13, bold=True, align="right")
        p.text(555, 60, f"Page {page_no} of 2", 8, align="right")
        p.line(40, 68, 555, 68, 1.2)
        meta = [
            ("Invoice No.", bill.number or ""),
            ("Date", bill.date or ""),
            (bill.po_label or "PO", bill.po_ref or ""),
        ]
        y = 84.0
        for label, value in meta:
            p.text(380, y, f"{label}:", 8.5, bold=True)
            p.text(450, y, value, 8.5)
            y += 12
        if page_no == 1:
            _party_block(p, 40, 84, "Sold by", BHARAT)
            _party_block(p, 220, 84, "Bill to", KESTREL)
            p.text(380, y + 2, "Place of supply: 29-Karnataka", 8)
        y = 170.0
        cols = _item_columns(bill, 40, 555)
        y = _table(p, y, 40, 555, cols, chunk)
        if page_no == 1:
            p.text(555, y + 14, "Continued on page 2", 8, align="right")
        else:
            y = _totals(p, bill, y + 16, 360, 555)
            p.text(40, y + 6, f"Amount in words: {bill.words}", 8)
            _bank(p, bill, 40, y + 26)
            p.text(555, y + 70, "For Bharat Office Supplies", 8.5, bold=True, align="right")
            p.text(555, y + 100, "Authorised Signatory", 8, align="right")
        c.showPage()
    c.save()
    return buf.getvalue(), bill


# A plain single-page layout reused for the scans (U02, U03) and the merged file (U09) ----------


def _plain_page(
    c: Canvas,
    bill: Bill,
    size: tuple[float, float] = A4,
    header: str = "left",
    font: str = "Helvetica",
    extra_totals: Sequence[tuple[str, str]] = (),
) -> None:
    p = Pen(c, size, font)
    w = size[0]
    if header == "center":
        p.text(w / 2, 48, bill.supplier.name, 16, bold=True, align="center")
        p.text(w / 2, 62, " · ".join(bill.supplier.address), 8, align="center")
        if bill.supplier.gstin:
            p.text(w / 2, 74, f"GSTIN {bill.supplier.gstin}", 8, align="center")
        p.text(w / 2, 96, bill.title or "", 12, bold=True, align="center")
        y = 116.0
    else:
        y = _party_block(p, 40, 44, None, bill.supplier, 9)
        p.text(w - 40, 50, bill.title or "", 14, bold=True, align="right")
        y = max(y, 100) + 8
    p.line(40, y, w - 40, y)
    y += 16
    _party_block(p, 40, y, "Bill to", bill.buyer)
    meta = [("Invoice No.", bill.number), ("Invoice Date", bill.date)]
    if bill.po_ref:
        meta.append((bill.po_label or "PO", bill.po_ref))
    if bill.place_of_supply:
        meta.append(("Place of Supply", bill.place_of_supply))
    my = y
    for label, value in meta:
        p.text(w - 230, my, f"{label}:", 9, bold=True)
        p.text(w - 140, my, value or "", 9)
        my += 13
    y = max(my, y + 60) + 14
    y = _table(p, y, 40, w - 40, _item_columns(bill, 40, w - 40), list(enumerate(bill.items, 1)))
    y = _totals(p, bill, y + 18, w - 230, w - 40, 9, extra_totals)
    if bill.words:
        p.text(40, y + 6, f"Amount in words: {bill.words}", 8.5)
    _bank(p, bill, 40, y + 26)
    p.text(w - 40, y + 70, f"For {bill.supplier.name}", 9, bold=True, align="right")
    p.text(w - 40, y + 98, "Authorised Signatory", 8, align="right")


def _plain_pdf(bill: Bill, **kw: Any) -> bytes:
    buf, c = _new_pdf(A4, f"Invoice {bill.number}")
    _plain_page(c, bill, **kw)
    c.showPage()
    c.save()
    return buf.getvalue()


# --- scan and photo effects ---------------------------------------------------------------------


def _raster(pdf: bytes, dpi: int) -> Image.Image:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _noise(img: Image.Image, rng: random.Random, sigma: float) -> Image.Image:
    size = 128
    tile = Image.frombytes(
        "L",
        (size, size),
        bytes(max(0, min(255, int(128 + rng.gauss(0, sigma)))) for _ in range(size * size)),
    )
    field_img = Image.new("L", img.size, 128)
    for ty in range(0, img.height, size):
        for tx in range(0, img.width, size):
            field_img.paste(tile, (tx, ty))
    return ImageChops.add(img, Image.merge("RGB", (field_img,) * 3), scale=1.0, offset=-128)


def _image_pdf(img: Image.Image, page: tuple[float, float], quality: int, title: str) -> bytes:
    jpeg = io.BytesIO()
    img.save(jpeg, "JPEG", quality=quality, optimize=False, progressive=False)
    jpeg.seek(0)
    buf, c = _new_pdf(page, title)
    c.setCreator("Scan")
    c.drawImage(ImageReader(jpeg), 0, 0, width=page[0], height=page[1])
    c.showPage()
    c.save()
    return buf.getvalue()


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination for the 8×8 perspective system (no numpy in the runtime)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col], strict=True)]
    return [m[i][n] / m[i][i] for i in range(n)]


def _perspective(
    src: Image.Image,
    quad: list[tuple[float, float]],
    size: tuple[int, int],
    fill: tuple[int, int, int],
) -> Image.Image:
    """Warp `src` so its corners land on `quad` (tl, tr, br, bl) in an image of `size`."""
    w, h = src.size
    corners = [(0, 0), (w, 0), (w, h), (0, h)]
    rows: list[list[float]] = []
    rhs: list[float] = []
    for (x, y), (u, v) in zip(quad, corners, strict=True):  # output (x, y) → source (u, v)
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.append(v)
    coeffs = _solve(rows, rhs)
    return src.transform(
        size, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC, fillcolor=fill
    )


def rotated_scan(pdf: bytes, index: int) -> bytes:
    """A page fed into the scanner sideways: landscape image, text running bottom to top."""
    rng = random.Random(SEED + index)
    img = _raster(pdf, 150)
    img = ImageChops.multiply(img, Image.new("RGB", img.size, (246, 244, 238)))
    img = img.rotate(90, resample=Image.Resampling.BICUBIC, expand=True)
    img = img.rotate(
        0.6, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(236, 236, 233)
    )
    img = _noise(img, rng, 7).filter(ImageFilter.GaussianBlur(0.45))
    return _image_pdf(img, landscape(A4), 72, "Scan")


def phone_photo(pdf: bytes, index: int) -> bytes:
    """A low-resolution phone photo: perspective skew, uneven light, a hand's shadow, JPEG."""
    rng = random.Random(SEED + index)
    page = _raster(pdf, 110)
    w, h = page.size
    out_w, out_h = int(w * 1.08), int(h * 1.06)
    quad = [
        (out_w * 0.09, out_h * 0.05),
        (out_w * 0.93, out_h * 0.02),
        (out_w * 0.97, out_h * 0.97),
        (out_w * 0.03, out_h * 0.94),
    ]
    photo = _perspective(page, quad, (out_w, out_h), (92, 78, 64))  # a wooden desk
    light = Image.linear_gradient("L").resize((out_w, out_h)).point(lambda v: 255 - v * 70 // 255)
    photo = ImageChops.multiply(photo, Image.merge("RGB", (light,) * 3))
    shadow = Image.new("L", (out_w, out_h), 255)
    ImageDraw.Draw(shadow).polygon(
        [(out_w * 0.62, out_h), (out_w, out_h * 0.58), (out_w, out_h)], fill=150
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(40))
    photo = ImageChops.multiply(photo, Image.merge("RGB", (shadow,) * 3))
    photo = ImageEnhance.Color(photo).enhance(0.85)
    photo = _noise(photo, rng, 9).filter(ImageFilter.GaussianBlur(0.7))
    return _image_pdf(photo, A4, 45, "IMG_20261117_183204")


# U02 — rotated scan ------------------------------------------------------------------------------

APEX = Party(
    "Apex Industrial Supplies",
    ["No. 23, SIDCO Industrial Estate, Guindy", "Chennai, Tamil Nadu 600032"],
    gstin="33AAPFA5560G1ZH",
    phone="+91 44 2625 1100",
    email="ar@apexindustrial.example",
)


def u02() -> tuple[bytes, Bill]:
    bill = Bill(
        doc_type="tax_invoice",
        title="TAX INVOICE",
        number="AIS/26-27/1241",
        date="17.11.2026",
        supplier=APEX,
        buyer=KESTREL,
        items=_items(
            [
                ("Safety goggles, anti-fog, clear", "9004", "40", "Nos", "185.00"),
                ("Ear plugs, corded, box of 100 pairs", "3926", "10", "Box", "960.00"),
            ]
        ),
        place_of_supply="29-Karnataka",
        bank={
            "holder": "Apex Industrial Supplies",
            "bank": "Indian Overseas Bank",
            "account": "078901234567890",
            "ifsc": "IOBA0000789",
        },
    )
    bill.taxes = _gst(bill.subtotal, Decimal(18), intra=False)
    _finish(bill)
    return rotated_scan(_plain_pdf(bill, header="center"), 2), bill


# U03 — phone photo -------------------------------------------------------------------------------

DECCAN = Party(
    "Deccan Cold Chain Logistics Pvt. Ltd.",
    ["No. 112, KIADB Industrial Area, Bommasandra", "Bengaluru, Karnataka 560099"],
    gstin="29AADCD7781K1Z1",
    phone="+91 80 4123 7788",
    email="billing@deccancoldchain.example",
)


def u03() -> tuple[bytes, Bill]:
    bill = Bill(
        doc_type="tax_invoice",
        title="TAX INVOICE",
        number="DCC/1196/26",
        date="17-11-2026",
        supplier=DECCAN,
        buyer=KESTREL,
        items=_items(
            [
                (
                    "Cold storage rental, per pallet-month, November 2026",
                    "996721",
                    "36",
                    "Pallet-month",
                    "950.00",
                ),
            ]
        ),
        place_of_supply="29-Karnataka",
        bank={
            "holder": "Deccan Cold Chain Logistics Pvt. Ltd.",
            "bank": "ICICI Bank",
            "account": "004501234567",
            "ifsc": "ICIC0000456",
        },
        legibility="partly_legible",
    )
    bill.taxes = _gst(bill.subtotal, Decimal(18), intra=True)
    _finish(bill)
    return phone_photo(_plain_pdf(bill), 3), bill


# U04 — unregistered small vendor, no GSTIN ------------------------------------------------------

GANESH = Party(
    "Shree Ganesh Repair Works",
    ["Shop 3, Ring Road, near Peenya Metro Station", "Bengaluru 560058"],
    phone="98450 66213",
)


def u04() -> tuple[bytes, Bill]:
    bill = Bill(
        doc_type="other",  # no heading: only "Bill No" and a total say it is a bill
        title=None,
        number="214",
        date="14/11/2026",
        supplier=GANESH,
        buyer=KESTREL_NO_GSTIN,
        items=[
            Item(
                "Repair of loading-dock shutter motor (labour)",
                None,
                None,
                None,
                Decimal("6500.00"),
            ),
            Item("Spares: capacitor, limit switch, wiring", None, None, None, Decimal("2350.00")),
        ],
        mark="Rs.",
        notes=["Not registered under GST. No GST charged."],
        show_subtotal=False,
    )
    bill.words = amount_in_words(bill.total)
    buf, c = _new_pdf((420, 595), "Bill 214")  # A5-ish cash-bill pad
    p = Pen(c, (420, 595), "Courier")
    p.rect(20, 20, 380, 555)
    p.text(210, 50, GANESH.name.upper(), 13, bold=True, align="center")
    p.text(210, 64, ", ".join(GANESH.address), 7.5, align="center")
    p.text(210, 76, f"Mob: {GANESH.phone}", 7.5, align="center")
    p.line(20, 86, 400, 86)
    p.text(32, 104, f"Bill No: {bill.number}", 9, bold=True)
    p.text(388, 104, f"Date: {bill.date}", 9, align="right")
    p.text(32, 124, f"To: {KESTREL.name}", 9)
    p.text(56, 136, KESTREL.address[0], 8)
    p.text(56, 147, KESTREL.address[1], 8)
    y = 170.0
    p.rect(32, y, 356, 16, fill=0.92)
    p.text(40, y + 11, "Particulars", 8.5, bold=True)
    p.text(380, y + 11, "Amount (Rs.)", 8.5, bold=True, align="right")
    y += 30
    for it in bill.items:
        p.text(40, y, it.description, 8)
        p.text(380, y, bill.money(it.amount), 8.5, align="right")
        y += 18
    p.line(32, y, 388, y)
    p.text(40, y + 16, "TOTAL", 10, bold=True)
    p.text(380, y + 16, bill.total_text(), 10, bold=True, align="right")
    p.text(32, y + 40, f"({bill.words})", 7.5)
    p.text(32, y + 62, bill.notes[0], 8, bold=True)
    p.text(32, y + 76, "Payment by cash or UPI to 98450 66213.", 8)
    p.text(388, y + 130, "for Shree Ganesh Repair Works", 8, align="right")
    c.showPage()
    c.save()
    return buf.getvalue(), bill


# U05 — foreign vendor in USD, no GST -------------------------------------------------------------

NORTHWIND = Party(
    "Northwind Data Labs Inc.",
    ["1420 Fifth Avenue, Suite 2200", "Seattle, WA 98101, USA"],
    phone="+1 206 555 0142",
    email="billing@northwinddata.example",
)


def _usd_words(v: Decimal) -> str:
    dollars = int(v)
    cents = int((v - dollars) * 100)
    text = num2words(dollars, lang="en").replace(",", "").title()
    return f"US Dollars {text} and {cents:02d}/100 Only"


def u05() -> tuple[bytes, Bill]:
    bill = Bill(
        doc_type="tax_invoice",
        title="INVOICE",
        number="NDL-2026-1107",
        date="Nov 15, 2026",
        due_date="Dec 15, 2026",
        supplier=NORTHWIND,
        buyer=KESTREL,
        items=[
            Item(
                "Data pipeline consulting, October 2026",
                Decimal(32),
                "hours",
                Decimal("150.00"),
                Decimal("4800.00"),
            ),
            Item(
                "Cloud compute pass-through (at cost)",
                Decimal(1),
                None,
                Decimal("412.50"),
                Decimal("412.50"),
            ),
        ],
        fmt=format_western,
        mark="USD",
        currency="USD",
        annotations=["Export of services - no Indian GST charged. Reverse charge may apply."],
        bank={
            "bank": "First Pacific Bank, Seattle",
            "account": "0004417726",
            "swift": "FPBKUS66",
            "routing": "125000105",
        },
    )
    bill.words = _usd_words(bill.total)
    buf, c = _new_pdf(LETTER, "Invoice NDL-2026-1107")
    p = Pen(c, LETTER, "Times-Roman")
    w = LETTER[0]
    p.text(54, 60, NORTHWIND.name, 18, bold=True)
    y = 76.0
    for ln in [*NORTHWIND.address, NORTHWIND.phone or "", NORTHWIND.email or ""]:
        p.text(54, y, ln, 9.5)
        y += 12
    p.text(w - 54, 60, "INVOICE", 22, bold=True, align="right")
    meta = [
        ("Invoice #", bill.number),
        ("Invoice date", bill.date),
        ("Due date", bill.due_date),
        ("Terms", "Net 30"),
    ]
    my = 84.0
    for label, value in meta:
        p.text(w - 200, my, label, 9.5, bold=True)
        p.text(w - 54, my, value or "", 9.5, align="right")
        my += 13
    y = 160.0
    p.text(54, y, "BILL TO", 9, bold=True)
    _party_block(p, 54, y + 12, None, KESTREL, 9.5)
    y = 250.0
    p.rect(54, y, w - 108, 18, fill=0.85)
    for head, x, align in (
        ("Description", 60, "left"),
        ("Qty", w - 250, "right"),
        ("Unit price (USD)", w - 150, "right"),
        ("Amount (USD)", w - 60, "right"),
    ):
        p.text(x, y + 12.5, head, 9.5, bold=True, align=align)
    y += 18
    for it in bill.items:
        p.text(60, y + 14, it.description, 9.5)
        p.text(w - 250, y + 14, f"{_qty(it.qty)} {it.uom or ''}".strip(), 9.5, align="right")
        p.text(w - 150, y + 14, bill.money(it.rate or Decimal()), 9.5, align="right")
        p.text(w - 60, y + 14, bill.money(it.amount), 9.5, align="right")
        y += 22
        p.line(54, y, w - 54, y, 0.3)
    y += 18
    p.text(w - 200, y, "Subtotal", 10)
    p.text(w - 60, y, bill.money(bill.subtotal), 10, align="right")
    p.text(w - 200, y + 15, "Tax", 10)
    p.text(w - 60, y + 15, "0.00", 10, align="right")
    p.text(w - 200, y + 34, "TOTAL DUE", 12, bold=True)
    p.text(w - 60, y + 34, bill.total_text(), 12, bold=True, align="right")
    p.text(54, y + 60, bill.words or "", 9)
    p.text(54, y + 80, bill.annotations[0], 9.5, bold=True)
    yb = _bank(p, bill, 54, y + 110, 9)
    p.text(54, yb + 20, "Please include the invoice number with your wire transfer.", 9)
    c.showPage()
    c.save()
    return buf.getvalue(), bill


# U06 — credit note against an earlier invoice ---------------------------------------------------

SHARMA = Party(
    "Sharma Packaging Industries",
    ["Plot 47, Bhosari MIDC", "Pune, Maharashtra 411026"],
    gstin="27AAKFS2231P1ZS",
    phone="+91 20 2712 4455",
    email="accounts@sharmapackaging.example",
)


def u06() -> tuple[bytes, Bill]:
    bill = Bill(
        doc_type="credit_note",
        title="CREDIT NOTE",
        number="SPI/CN/26-27/012",
        date="16/11/2026",
        supplier=SHARMA,
        buyer=KESTREL,
        items=_items(
            [
                (
                    "Corrugated shipper box 450x300x250 mm, 5-ply (damaged in transit, returned)",
                    "4819",
                    "40",
                    "Nos",
                    "38.50",
                ),
            ]
        ),
        mark="Rs.",
        place_of_supply="29-Karnataka",
    )
    bill.taxes = _gst(bill.subtotal, Decimal(18), intra=False)
    _finish(bill)
    buf, c = _new_pdf(A4, "Credit note SPI/CN/26-27/012")
    p = Pen(c, A4)
    p.rect(40, 36, 515, 54, fill=0.15)
    c.setFillGray(1)
    p.text(56, 60, SHARMA.name, 15, bold=True)
    p.text(56, 76, f"GSTIN {SHARMA.gstin}  ·  {', '.join(SHARMA.address)}", 8)
    p.text(540, 64, "CREDIT NOTE", 14, bold=True, align="right")
    c.setFillGray(0)
    meta = [
        ("Credit Note No.", bill.number),
        ("Date", bill.date),
        ("Against Invoice", "SPI/26-27/0198 dated 20/10/2026"),
        ("Reason", "Short / damaged supply"),
    ]
    y = 112.0
    for label, value in meta:
        p.text(330, y, f"{label}:", 9, bold=True)
        p.text(420, y, value or "", 9)
        y += 13
    _party_block(p, 40, 112, "Issued to", KESTREL, 9)
    y = 190.0
    y = _table(p, y, 40, 555, _item_columns(bill, 40, 555), list(enumerate(bill.items, 1)))
    y = _totals(p, bill, y + 18, 340, 555, 9)
    p.text(40, y + 8, f"Amount in words: {bill.words}", 8.5)
    p.text(40, y + 30, "This credit will be adjusted against your outstanding dues.", 8.5)
    p.text(555, y + 70, "For Sharma Packaging Industries", 9, bold=True, align="right")
    c.showPage()
    c.save()
    return buf.getvalue(), bill


# U07 — e-invoice with IRN and QR block ----------------------------------------------------------

VERTEX = Party(
    "Vertex Lab Instruments Pvt. Ltd.",
    ["Plot 9, GIDC Estate, Vatva", "Ahmedabad, Gujarat 382445"],
    gstin="24AACCV6672E1ZB",
    phone="+91 79 2658 3300",
    email="accounts@vertexlab.example",
)
U07_IRN = hashlib.sha256(b"VLI/26-27/0334|24AACCV6672E1ZB|2026-27").hexdigest()


def _qr_placeholder(
    c: Canvas, x: float, y_top: float, size: float, page_h: float, rng: random.Random
) -> None:
    """A QR-like block (not a real code): three finder squares and a seeded module pattern."""
    n = 25
    cell = size / n

    def box(i: int, j: int, k: int, gray: float) -> None:
        c.setFillGray(gray)
        c.rect(x + j * cell, page_h - y_top - (i + k) * cell, k * cell, k * cell, stroke=0, fill=1)

    for i in range(n):
        for j in range(n):
            if (i < 8 and j < 8) or (i < 8 and j >= n - 8) or (i >= n - 8 and j < 8):
                continue
            if rng.random() < 0.48:
                box(i, j, 1, 0)
    for i, j in ((0, 0), (0, n - 7), (n - 7, 0)):
        box(i, j, 7, 0)
        box(i + 1, j + 1, 5, 1)
        box(i + 2, j + 2, 3, 0)
    c.setFillGray(0)


def u07() -> tuple[bytes, Bill]:
    bill = Bill(
        doc_type="tax_invoice",
        title="TAX INVOICE",
        number="VLI/26-27/0334",
        date="14/11/2026",
        supplier=VERTEX,
        buyer=KESTREL,
        items=_items(
            [
                ("HPLC column C18, 250 x 4.6 mm, 5 micron", "9027", "2", "Nos", "38500.00"),
                ("Guard cartridge kit for C18 column", "9027", "1", "Set", "6200.00"),
            ]
        ),
        mark="Rs.",
        place_of_supply="29-Karnataka",
        bank={
            "holder": "Vertex Lab Instruments Pvt. Ltd.",
            "bank": "HDFC Bank",
            "account": "50200087654321",
            "ifsc": "HDFC0000567",
        },
    )
    bill.taxes = _gst(bill.subtotal, Decimal(18), intra=False)
    _finish(bill)
    rng = random.Random(SEED + 7)
    buf, c = _new_pdf(A4, "e-Invoice VLI/26-27/0334")
    p = Pen(c, A4)
    p.text(297, 40, "e-Invoice", 9, align="center")
    p.text(297, 56, "TAX INVOICE", 13, bold=True, align="center")
    p.rect(40, 66, 515, 92)
    p.text(50, 82, f"IRN: {U07_IRN}", 7.5, font="Courier")
    p.text(50, 96, "Ack No.: 112625890034517", 8.5)
    p.text(50, 109, "Ack Date: 14-11-2026 10:42", 8.5)
    p.text(50, 122, "e-Way Bill No.: 3610 2245 7781", 8.5)
    p.text(50, 140, "Signed by the Invoice Registration Portal (IRP)", 7.5)
    _qr_placeholder(c, 470, 70, 82, A4[1], rng)
    y = _party_block(p, 40, 176, "Supplier", VERTEX, 8.5)
    _party_block(p, 300, 176, "Recipient", KESTREL, 8.5)
    meta = [
        ("Document No.", bill.number),
        ("Document Date", bill.date),
        ("Supply Type", "B2B"),
        ("Place of Supply", "29-Karnataka"),
        ("Reverse Charge", "No"),
    ]
    y = max(y, 250) + 6
    for i, (label, value) in enumerate(meta):
        x = 40 + (i % 3) * 172
        yy = y + (i // 3) * 13
        p.text(x, yy, f"{label}: {value}", 8.5)
    y += 34
    y = _table(p, y, 40, 555, _item_columns(bill, 40, 555), list(enumerate(bill.items, 1)))
    y = _totals(p, bill, y + 18, 340, 555, 9)
    p.text(40, y + 8, f"Amount in words: {bill.words}", 8.5)
    _bank(p, bill, 40, y + 28)
    p.text(555, y + 80, "Digitally signed by VERTEX LAB INSTRUMENTS", 8, align="right")
    c.showPage()
    c.save()
    return buf.getvalue(), bill


# U08 — trade discount line and TCS --------------------------------------------------------------


def u08() -> tuple[bytes, Bill]:
    boxes = Item(
        "Corrugated shipper box 450x300x250 mm, 5-ply",
        Decimal(1000),
        "Nos",
        Decimal("38.50"),
        Decimal("38500.00"),
        hsn="4819",
    )
    discount = Item("Less: Trade discount @ 5%", None, None, None, Decimal("-1925.00"))
    bill = Bill(
        doc_type="tax_invoice",
        title="TAX INVOICE",
        number="SPI/26-27/0247",
        date="17/11/2026",
        supplier=SHARMA,
        buyer=KESTREL,
        items=[boxes, discount],
        mark="Rs.",
        po_label="PO No.",
        po_ref="KF-PO-0163",
        place_of_supply="29-Karnataka",
        bank={
            "holder": "Sharma Packaging Industries",
            "bank": "HDFC Bank",
            "account": "50200012345678",
            "ifsc": "HDFC0000123",
        },
    )
    taxable = bill.subtotal
    bill.taxes = _gst(taxable, Decimal(18), intra=False)
    tcs_base = taxable + bill.taxes[0].amount
    bill.taxes.append(Tax("OTHER", Decimal("0.1"), q2(tcs_base / 1000), "TCS u/s 206C(1H) @ 0.1%"))
    _finish(bill)
    pdf = _plain_pdf(bill, header="center", font="Times-Roman")
    return pdf, bill


# U09 — two invoices in one PDF ------------------------------------------------------------------

RAO = Party(
    "Rao & Sons Electricals",
    ["6-3-1192, Begumpet Main Road", "Hyderabad, Telangana 500016"],
    gstin="36ABCPR4410H1ZV",
    phone="+91 40 2766 5544",
    email="raoandsons.electricals@mail.example",
)
RAO_BANK = {
    "holder": "Rao & Sons Electricals",
    "bank": "State Bank of India",
    "account": "30987654321",
    "ifsc": "SBIN0020345",
}


def _rao(number: str, date: str, po: str, items: list[Item]) -> Bill:
    bill = Bill(
        doc_type="tax_invoice",
        title="TAX INVOICE",
        number=number,
        date=date,
        supplier=RAO,
        buyer=KESTREL,
        items=items,
        po_label="P.O.",
        po_ref=po,
        place_of_supply="29-Karnataka",
        bank=RAO_BANK,
    )
    bill.taxes = _gst(bill.subtotal, Decimal(18), intra=False)
    return _finish(bill)


def u09() -> tuple[bytes, Bill]:
    first = _rao(
        "RSE/0466",
        "13/11/2026",
        "163",
        _items([("LED tube light 20W, 4 ft", "9405", "40", "Nos", "240.00")]),
    )
    second = _rao(
        "RSE/0467",
        "13/11/2026",
        "164",
        _items([("Exhaust fan 300 mm, heavy duty", "8414", "6", "Nos", "2150.00")]),
    )
    buf, c = _new_pdf(A4, "Invoices RSE/0466-0467")
    for bill in (first, second):
        _plain_page(c, bill)
        c.showPage()
    c.save()
    return buf.getvalue(), first


# U10 — not an invoice: a delivery challan -------------------------------------------------------


def u10() -> tuple[bytes, Bill]:
    items = [
        Item(
            "Corrugated shipper box 450x300x250 mm, 5-ply",
            Decimal(2000),
            "Nos",
            None,
            Decimal(0),
            hsn="4819",
        ),
        Item(
            "BOPP packing tape 48 mm x 65 m, brown",
            Decimal(300),
            "Roll",
            None,
            Decimal(0),
            hsn="3919",
        ),
    ]
    bill = Bill(
        doc_type="other",
        title="DELIVERY CHALLAN",
        number="SPI/DC/26-27/0388",
        date="10/11/2026",
        supplier=SHARMA,
        buyer=KESTREL,
        items=items,
        po_label="PO No.",
        po_ref="KF-PO-0142",
        mark="",
        currency=None,
        show_subtotal=False,
        priced=False,
        annotations=["Goods sent for supply against PO. Not for sale."],
    )
    buf, c = _new_pdf(A4, "Delivery challan SPI/DC/26-27/0388")
    p = Pen(c, A4)
    p.text(297, 44, SHARMA.name, 15, bold=True, align="center")
    p.text(297, 58, ", ".join(SHARMA.address) + f"  ·  GSTIN {SHARMA.gstin}", 8, align="center")
    p.rect(200, 70, 195, 22, fill=0.88)
    p.text(297, 85, "DELIVERY CHALLAN", 12, bold=True, align="center")
    meta = [
        ("Challan No.", bill.number),
        ("Date", bill.date),
        ("PO No.", bill.po_ref),
        ("Vehicle No.", "MH 14 KQ 4417"),
        ("Transporter", "Shree Balaji Roadlines"),
        ("LR No.", "SBR/88214"),
    ]
    y = 112.0
    for i, (label, value) in enumerate(meta):
        x = 40 if i < 3 else 320
        yy = y + (i % 3) * 14
        p.text(x, yy, f"{label}: {value}", 9)
    _party_block(p, 40, 166, "Consignee", KESTREL, 9)
    y = 236.0
    p.rect(40, y, 515, 16, fill=0.9)
    for head, x, align in (
        ("#", 46, "left"),
        ("Description of goods", 66, "left"),
        ("HSN", 380, "left"),
        ("Quantity", 470, "right"),
        ("Unit", 480, "left"),
    ):
        p.text(x, y + 11, head, 8.5, bold=True, align=align)
    y += 16
    for n, it in enumerate(items, 1):
        p.text(46, y + 12, str(n), 8.5)
        p.text(66, y + 12, it.description, 8.5)
        p.text(380, y + 12, it.hsn or "", 8.5)
        p.text(470, y + 12, _qty(it.qty) or "", 8.5, align="right")
        p.text(480, y + 12, it.uom or "", 8.5)
        y += 18
    p.line(40, y, 555, y)
    p.text(40, y + 22, bill.annotations[0], 9, bold=True)
    p.text(40, y + 36, "No commercial value. The tax invoice will follow separately.", 8.5)
    p.rect(40, y + 60, 240, 70)
    p.text(48, y + 74, "Received the above goods in good condition", 8)
    p.text(48, y + 120, "Receiver's signature & stamp", 8)
    p.text(555, y + 120, "For Sharma Packaging Industries", 8.5, bold=True, align="right")
    c.showPage()
    c.save()
    return buf.getvalue(), bill


# --- the pack -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StressDoc:
    doc_id: str
    title: str
    unusual: str
    tags: tuple[str, ...]
    build: Callable[[], tuple[bytes, Bill]]
    expected: dict[str, Any]
    sender: tuple[str, str]
    subject: str
    received_at: str


def _exp(
    outcome: str,
    route: str,
    required: list[str],
    allowed: list[str] | None = None,
    live: list[str] | None = None,
) -> dict[str, Any]:
    """Expected result with a perfect reading; `live_also` lists codes a live reading may add
    (e.g. low confidence on a photo)."""
    return {
        "outcome": outcome,
        "route": route,
        "required": required,
        "allowed": allowed or [],
        "live_also": live or [],
    }


STRESS: tuple[StressDoc, ...] = (
    StressDoc(
        "U01",
        "Two-page invoice, 28 lines, totals on page 2",
        "28 line items over two pages; the totals, tax and bank details are only on page 2",
        ("stress", "multi-page", "digital"),
        u01,
        _exp("HOLD", "buyer", ["PO_NOT_FOUND"], ["LINE_NOT_ON_PO", "ROUND_OFF_APPLIED"]),
        ("Bharat Office Supplies", "sales@bharatoffice.example"),
        "Invoice BOS/2627/0602 (2 pages)",
        "2026-11-18T11:05:00+05:30",
    ),
    StressDoc(
        "U02",
        "Scan fed in sideways (rotated 90°)",
        "an image-only scan with the page rotated 90°, so the text runs bottom to top",
        ("stress", "scanned", "rotated"),
        u02,
        _exp("HOLD", "buyer", ["PO_MISSING"], ["PO_INFERRED"], ["FIELD_LOW_CONFIDENCE"]),
        ("Apex Industrial Supplies", "ar@apexindustrial.example"),
        "Scan of invoice AIS/26-27/1241",
        "2026-11-17T15:20:00+05:30",
    ),
    StressDoc(
        "U03",
        "Phone photo: skewed, low resolution, shadow",
        "a 110 dpi phone photo with perspective skew, uneven light and a shadow across a "
        "corner, on a desk background",
        ("stress", "scanned", "photo"),
        u03,
        _exp("HOLD", "ap_clerk", ["PO_INFERRED"], [], ["FIELD_LOW_CONFIDENCE"]),
        ("Deccan Cold Chain Accounts", "billing@deccancoldchain.example"),
        "Photo of November storage bill",
        "2026-11-17T18:40:00+05:30",
    ),
    StressDoc(
        "U04",
        "Unregistered small vendor, no GSTIN",
        "a local repair shop's cash bill: no GSTIN for either party, no GST charged, no "
        "line quantities",
        ("stress", "unregistered", "no-gst"),
        u04,
        _exp("HOLD", "procurement", ["VENDOR_NOT_FOUND"], ["PO_MISSING"]),
        ("Shree Ganesh Repair Works", "ganeshrepairs.blr@mail.example"),
        "Bill for shutter repair",
        "2026-11-14T17:10:00+05:30",
    ),
    StressDoc(
        "U05",
        "Foreign vendor billing in USD, no GST",
        "a US vendor's invoice in USD on Letter paper, month-first dates, no GST "
        "(export of services), wire details with SWIFT instead of IFSC",
        ("stress", "foreign-currency", "no-gst"),
        u05,
        _exp("HOLD", "procurement", ["VENDOR_NOT_FOUND", "CURRENCY_MISMATCH"], ["PO_MISSING"]),
        ("Northwind Data Labs", "billing@northwinddata.example"),
        "Invoice NDL-2026-1107 - October consulting",
        "2026-11-16T07:30:00+05:30",
    ),
    StressDoc(
        "U06",
        "Credit note against an earlier invoice",
        "a credit note (not a bill) for damaged boxes, quoting the original invoice SPI/26-27/0198",
        ("stress", "credit-note"),
        u06,
        _exp("HOLD", "ap_clerk", ["DOC_CREDIT_NOTE"], ["ROUND_OFF_APPLIED"]),
        ("Sharma Packaging Accounts", "accounts@sharmapackaging.example"),
        "Credit note SPI/CN/26-27/012",
        "2026-11-16T12:15:00+05:30",
    ),
    StressDoc(
        "U07",
        "e-Invoice with IRN and QR code",
        "a GST e-invoice: 64-character IRN, acknowledgement number and date, e-way bill "
        "number and a QR block above the invoice fields",
        ("stress", "e-invoice", "digital"),
        u07,
        _exp("HOLD", "buyer", ["PO_MISSING"], ["PO_INFERRED"]),
        ("Vertex Lab Accounts", "accounts@vertexlab.example"),
        "e-Invoice VLI/26-27/0334",
        "2026-11-14T11:00:00+05:30",
    ),
    StressDoc(
        "U08",
        "Trade discount line and TCS",
        "a negative trade-discount line inside the item table, GST on the discounted "
        "value and TCS at 0.1% on top of GST",
        ("stress", "discount", "tcs"),
        u08,
        _exp("HOLD", "buyer", ["PO_NOT_FOUND"], ["ROUND_OFF_APPLIED"]),
        ("Sharma Packaging Accounts", "accounts@sharmapackaging.example"),
        "Invoice SPI/26-27/0247",
        "2026-11-17T10:25:00+05:30",
    ),
    StressDoc(
        "U09",
        "Two invoices in one PDF",
        "two separate one-page invoices (RSE/0466 and RSE/0467) scanned into a single file",
        ("stress", "multiple-invoices"),
        u09,
        _exp("HOLD", "ap_clerk", ["DOC_MULTIPLE_INVOICES"]),
        ("Rao & Sons Electricals", "raoandsons.electricals@mail.example"),
        "Bills RSE/0466 and 0467",
        "2026-11-13T16:45:00+05:30",
    ),
    StressDoc(
        "U10",
        "Not an invoice: delivery challan",
        "a delivery challan for goods sent against KF-PO-0142: quantities only, no prices "
        "and no tax",
        ("stress", "not-an-invoice"),
        u10,
        _exp("REJECT", "none", ["DOC_NOT_INVOICE"]),
        ("Sharma Packaging Dispatch", "accounts@sharmapackaging.example"),
        "Delivery challan SPI/DC/26-27/0388",
        "2026-11-10T09:50:00+05:30",
    ),
)


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline=""
    )


def generate_unseen(out: Path, index: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Write U01–U10 under `out/unseen/`, their truth under `out/truth/`. Returns manifest
    entries (kind "stress"); adds each document's hash to `index` when given."""
    folder = out / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (out / "truth").mkdir(parents=True, exist_ok=True)
    docs: dict[str, dict[str, Any]] = {}
    for spec in STRESS:
        pdf, bill = spec.build()
        rel = f"{FOLDER}/{spec.doc_id}.pdf"
        (out / rel).write_bytes(pdf)
        sha = hashlib.sha256(pdf).hexdigest()
        truth = {
            "doc_id": spec.doc_id,
            "kind": "stress",
            "render": "scanned" if {"scanned"} & set(spec.tags) else "digital",
            "template": "stress",
            "unusual": spec.unusual,
            "raw": raw_from(bill),
            "expected": spec.expected,
        }
        _write_json(out / "truth" / f"{spec.doc_id}.json", truth)
        if index is not None:
            index.setdefault(sha, spec.doc_id)
        docs[spec.doc_id] = {
            "file": rel,
            "sha256": sha,
            "kind": "stress",
            "title": spec.title,
            "edge_case": spec.unusual,
            "unusual": spec.unusual,
            "tags": list(spec.tags),
            "vendor_id": None,
            "template": "stress",
            "render": truth["render"],
            "copy_of": None,
            "email": {
                "sender_name": spec.sender[0],
                "sender_email": spec.sender[1],
                "subject": spec.subject,
                "received_at": spec.received_at,
            },
            "processed_at": None,
            "review": None,
            "review_if_raised": None,
            "awaiting_review": False,
            "expected": spec.expected,
        }
    return docs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the unseen stress documents.")
    parser.add_argument("--out", type=Path, default=None, help="world directory (DATA_DIR/demo)")
    args = parser.parse_args(argv)
    out = args.out or get_settings().data_dir / "demo"
    docs = generate_unseen(out)
    print(f"Wrote {len(docs)} stress documents to {out / FOLDER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
