"""Scenario specs → computed figures → the exact strings printed on an invoice, plus ground truth.

Templates draw only what is in `PrintedInvoice`, and the ground-truth `RawInvoice` is built from
the same object, so the PDF and its truth can't drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from app.enums import DocType
from app.models.extraction import RawInvoice, RawLine, RawTaxLine
from app.models.reference import Company, GoodsReceipt, POLine, PurchaseOrder, Vendor

from .money import amount_in_words, format_amount, format_signed, q2, round_off

DEMO_DIR = Path(__file__).resolve().parent
WORLD_PATH = DEMO_DIR / "world.yaml"
SCENARIOS_PATH = DEMO_DIR / "scenarios.yaml"

DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d-%b-%Y", "%d/%m/%y")
RUPEE_SIGN = "₹"


# --- World -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    company: Company
    states: dict[str, str]
    vendors: dict[str, Vendor]
    purchase_orders: dict[str, PurchaseOrder]
    goods_receipts: list[GoodsReceipt]


def load_world(path: Path = WORLD_PATH) -> World:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    states = {str(k): v for k, v in data["states"].items()}
    vendors: dict[str, Vendor] = {}
    for v in data["vendors"]:
        gstin = v["gstin"]
        vendors[v["vendor_id"]] = Vendor.model_validate(
            {**v, "pan": gstin[2:12], "state_code": gstin[:2]}
        )
    pos: dict[str, PurchaseOrder] = {}
    for p in data["purchase_orders"]:
        lines = [
            POLine(
                line_no=ln[0],
                item_code=ln[1],
                description=ln[2],
                quantity=Decimal(ln[3]),
                uom=ln[4],
                unit_price=Decimal(ln[5]),
                tax_rate_pct=Decimal(ln[6]),
                hsn_sac=ln[7],
                gl_account=ln[8],
            )
            for ln in p["lines"]
        ]
        pos[p["po_number"]] = PurchaseOrder.model_validate(
            {**{k: v for k, v in p.items() if k != "lines"}, "status": "open", "lines": lines}
        )
    grns = [
        GoodsReceipt(
            grn_number=g[0],
            po_number=g[1],
            line_no=g[2],
            quantity_received=Decimal(g[3]),
            received_date=g[4],
        )
        for g in data["goods_receipts"]
    ]
    return World(Company.model_validate(data["company"]), states, vendors, pos, grns)


# --- Styles and suppliers ----------------------------------------------------------------------


@dataclass(frozen=True)
class Style:
    template: str
    date_format: str
    amounts: str
    currency_mark: str
    po_label: str
    po_format: str
    total_suffix: str | None = None
    accent: str | None = None
    tagline: str | None = None


@dataclass(frozen=True)
class Bank:
    bank_name: str
    account: str
    ifsc: str


@dataclass(frozen=True)
class Supplier:
    key: str
    vendor_id: str | None
    legal_name: str
    gstin: str
    address: str
    city: str
    state_code: str
    phone: str
    email: str
    bank: Bank


def supplier_for(key: str, world: World, extra: dict[str, Any]) -> Supplier:
    if key in world.vendors:
        v = world.vendors[key]
        return Supplier(
            key=key,
            vendor_id=v.vendor_id,
            legal_name=v.legal_name,
            gstin=v.gstin,
            address=v.address,
            city=v.city,
            state_code=v.state_code,
            phone=v.phone_on_file,
            email=v.email,
            bank=Bank(v.bank_name, v.bank_account_number, v.bank_ifsc),
        )
    s = extra[key]
    return Supplier(
        key=key,
        vendor_id=None,
        legal_name=s["legal_name"],
        gstin=s["gstin"],
        address=s["address"],
        city=s["city"],
        state_code=s["state_code"],
        phone=s["phone"],
        email=s["email"],
        bank=Bank(**s["bank"]),
    )


# --- Document specs -----------------------------------------------------------------------------


@dataclass(frozen=True)
class LineSpec:
    code: str | None
    desc: str
    hsn: str
    qty: Decimal
    uom: str | None
    rate: Decimal
    tax_rate: Decimal
    po_line: int | None


@dataclass(frozen=True)
class Mark:
    """A stamp or handwritten note placed on a scanned page."""

    text: str
    color: str
    at: tuple[float, float]
    angle: float = 0.0


@dataclass(frozen=True)
class ScanSpec:
    dpi: int
    rotate: float
    noise: float
    blur: float
    jpeg_quality: int
    shadow: str
    handwriting: tuple[Mark, ...]
    stamps: tuple[Mark, ...]


@dataclass
class DocSpec:
    id: str
    kind: str  # "inbox" | "history"
    index: int
    supplier: Supplier
    style: Style
    render: str
    scan: ScanSpec | None
    po_number: str | None
    title: str
    number: str | None
    date_text: str
    po_ref: str | None
    tax: str  # "IGST" | "CGST_SGST"
    prices_include_tax: bool
    lines: list[LineSpec]
    bank: Bank
    phone: str
    supplier_email: str
    notes: list[str]
    notices: list[str]
    copy_of: str | None
    meta: dict[str, Any] = field(default_factory=dict)


def parse_printed_date(text: str, preferred: str | None = None) -> date:
    formats = (preferred, *DATE_FORMATS) if preferred else DATE_FORMATS
    for fmt in formats:
        if fmt is None:
            continue
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable printed date: {text!r}")


def _po_ref_default(style: Style, po_number: str | None) -> str | None:
    if po_number is None:
        return None
    return style.po_format.format(po=po_number, n=po_number.rsplit("-", 1)[-1])


def _line_spec(raw: dict[str, Any], po: PurchaseOrder | None) -> LineSpec:
    base: dict[str, Any] = {}
    if "po_line" in raw:
        if po is None:
            raise ValueError("po_line given but the document has no PO")
        pl = next(ln for ln in po.lines if ln.line_no == raw["po_line"])
        base = {
            "code": pl.item_code,
            "desc": pl.description,
            "hsn": pl.hsn_sac,
            "qty": str(pl.quantity),
            "uom": pl.uom,
            "rate": str(pl.unit_price),
            "tax_rate": str(pl.tax_rate_pct),
        }
    merged = {**base, **raw}
    return LineSpec(
        code=merged.get("code"),
        desc=merged["desc"],
        hsn=str(merged["hsn"]),
        qty=Decimal(str(merged["qty"])),
        uom=merged.get("uom"),
        rate=Decimal(str(merged["rate"])),
        tax_rate=Decimal(str(merged["tax_rate"])),
        po_line=raw.get("po_line"),
    )


def _marks(items: list[dict[str, Any]] | None) -> tuple[Mark, ...]:
    return tuple(
        Mark(text=m["text"], color=m["color"], at=(m["at"][0], m["at"][1]), angle=m.get("angle", 0))
        for m in items or []
    )


def _scan_spec(raw: dict[str, Any] | None) -> ScanSpec | None:
    if raw is None:
        return None
    return ScanSpec(
        dpi=int(raw["dpi"]),
        rotate=float(raw["rotate"]),
        noise=float(raw["noise"]),
        blur=float(raw.get("blur", 0)),
        jpeg_quality=int(raw["jpeg_quality"]),
        shadow=raw.get("shadow", "none"),
        handwriting=_marks(raw.get("handwriting")),
        stamps=_marks(raw.get("stamps")),
    )


def load_specs(world: World, path: Path = SCENARIOS_PATH) -> list[DocSpec]:
    """All documents: inbox S01–S15 then history in processing order."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    styles = {k: Style(**v) for k, v in data["styles"].items()}
    extra = data.get("suppliers", {})
    specs: list[DocSpec] = []
    entries = [("inbox", e) for e in data["inbox"]] + [("history", e) for e in data["history"]]
    by_id: dict[str, dict[str, Any]] = {e["id"]: e for _, e in entries}
    for index, (kind, entry) in enumerate(entries):
        source = by_id[entry["copy_of"]] if entry.get("copy_of") else entry
        supplier = supplier_for(entry["supplier"], world, extra)
        style = styles[entry["supplier"]]
        inv = source["invoice"]
        po_number = source.get("po")
        po = world.purchase_orders.get(po_number) if po_number else None
        bank_raw = inv.get("bank", "master")
        meta = {
            k: v
            for k, v in entry.items()
            if k not in {"invoice", "supplier", "po", "render", "scan", "copy_of"}
        }
        specs.append(
            DocSpec(
                id=entry["id"],
                kind=kind,
                index=index,
                supplier=supplier,
                style=style,
                render=source.get("render", "digital"),
                scan=_scan_spec(source.get("scan")),
                po_number=po_number,
                title=inv.get("title", "TAX INVOICE"),
                number=inv["number"],
                date_text=inv["date"],
                po_ref=inv["po_ref"] if "po_ref" in inv else _po_ref_default(style, po_number),
                tax=inv["tax"],
                prices_include_tax=bool(inv.get("prices_include_tax", False)),
                lines=[_line_spec(ln, po) for ln in inv["lines"]],
                bank=supplier.bank if bank_raw == "master" else Bank(**bank_raw),
                phone=inv.get("phone", supplier.phone),
                supplier_email=inv.get("supplier_email", supplier.email),
                notes=list(inv.get("notes", [])),
                notices=list(inv.get("notices", [])),
                copy_of=entry.get("copy_of"),
                meta=meta,
            )
        )
    return specs


# --- Figures ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LineFigures:
    amount: Decimal  # as printed: qty × rate (gross when prices include tax)
    taxable: Decimal


@dataclass(frozen=True)
class TaxFigure:
    tax_type: str
    rate_pct: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Figures:
    lines: list[LineFigures]
    subtotal: Decimal  # taxable value
    taxes: list[TaxFigure]
    round_off: Decimal
    total: Decimal

    def tax_total(self, tax_type: str | None = None) -> Decimal:
        return q2(sum((t.amount for t in self.taxes if tax_type in (None, t.tax_type)), Decimal()))


def compute(spec: DocSpec) -> Figures:
    lines: list[LineFigures] = []
    by_rate: dict[Decimal, tuple[Decimal, Decimal]] = {}  # rate → (taxable, gross)
    for ln in spec.lines:
        amount = q2(ln.qty * ln.rate)
        taxable = q2(amount / (1 + ln.tax_rate / 100)) if spec.prices_include_tax else amount
        lines.append(LineFigures(amount, taxable))
        t, g = by_rate.get(ln.tax_rate, (Decimal(), Decimal()))
        by_rate[ln.tax_rate] = (t + taxable, g + amount)
    taxes: list[TaxFigure] = []
    for rate in sorted(by_rate):
        taxable, gross = by_rate[rate]
        if spec.tax == "IGST":
            amt = gross - taxable if spec.prices_include_tax else q2(taxable * rate / 100)
            taxes.append(TaxFigure("IGST", rate, q2(amt)))
        else:
            half = rate / 2
            if spec.prices_include_tax:
                tax = q2(gross - taxable)
                cgst = q2(tax / 2)
                sgst = tax - cgst
            else:
                cgst = sgst = q2(taxable * half / 100)
            taxes.append(TaxFigure("CGST", half, cgst))
            taxes.append(TaxFigure("SGST", half, sgst))
    subtotal = q2(sum((ln.taxable for ln in lines), Decimal()))
    exact = subtotal + sum((t.amount for t in taxes), Decimal())
    total, delta = round_off(exact)
    return Figures(lines, subtotal, taxes, delta, total)


# --- Printed strings ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Caps:
    """What a template prints. Anything a template doesn't print is null in the truth."""

    item_code: bool
    line_tax_rate: bool


@dataclass(frozen=True)
class PrintedLine:
    sl: str
    description: str
    item_code: str | None
    hsn_sac: str
    quantity: str
    uom: str | None
    unit_price: str
    amount: str
    tax_rate: str | None


@dataclass(frozen=True)
class PrintedTax:
    tax_type: str
    rate: str
    amount: str


@dataclass(frozen=True)
class PrintedHsn:
    hsn: str
    taxable: str
    taxes: list[PrintedTax]
    total_tax: str


@dataclass(frozen=True)
class PrintedInvoice:
    doc_id: str
    title: str
    number: str | None
    date: str
    po_label: str
    po_ref: str | None
    supplier_name: str
    supplier_address_lines: tuple[str, str]
    supplier_gstin: str
    supplier_pan: str
    supplier_state: str
    supplier_phone: str
    supplier_email: str
    buyer_name: str
    buyer_address_lines: tuple[str, str]
    buyer_gstin: str
    buyer_state: str
    place_of_supply: str
    currency_mark: str
    lines: list[PrintedLine]
    subtotal: str | None
    taxes: list[PrintedTax]
    round_off: str | None
    total: str
    total_value: str  # total without the currency mark
    amount_in_words: str
    prices_include_tax: bool
    inclusive_note: str | None
    bank_name: str
    bank_account_name: str
    bank_account: str
    bank_ifsc: str
    notes: list[str]
    notices: list[str]
    tagline: str | None
    accent: str | None
    payment_terms_days: int | None
    hsn_rows: list[PrintedHsn]
    hsn_total: PrintedHsn

    @property
    def supplier_address(self) -> str:
        return " ".join(self.supplier_address_lines)


def split_address(address: str) -> tuple[str, str]:
    """'Plot 47, Bhosari MIDC, Pune, Maharashtra 411026' → ('Plot 47, Bhosari MIDC,', 'Pune, …')."""
    parts = address.split(", ")
    head, tail = parts[:-2], parts[-2:]
    return (", ".join(head) + ",", ", ".join(tail))


def format_rate_pct(rate: Decimal) -> str:
    text = format(rate.normalize(), "f")
    return f"{text}%"


def resolve_mark(style: Style, rupee_ok: bool) -> str:
    if style.currency_mark == RUPEE_SIGN and not rupee_ok:
        return "Rs."
    return style.currency_mark


def _hsn_rows(spec: DocSpec, figures: Figures, fmt: str) -> tuple[list[PrintedHsn], PrintedHsn]:
    """HSN-wise tax summary. The last row absorbs any paisa difference so columns add up."""
    groups: dict[tuple[str, Decimal], Decimal] = {}
    for ln, lf in zip(spec.lines, figures.lines, strict=True):
        key = (ln.hsn, ln.tax_rate)
        groups[key] = groups.get(key, Decimal()) + lf.taxable
    remaining = {(t.tax_type, t.rate_pct): t.amount for t in figures.taxes}
    rows: list[PrintedHsn] = []
    keys = list(groups)
    for i, (hsn, rate) in enumerate(keys):
        taxable = groups[(hsn, rate)]
        taxes: list[PrintedTax] = []
        total = Decimal()
        for t in figures.taxes:
            if t.rate_pct * (2 if t.tax_type != "IGST" else 1) != rate:
                continue
            last = all(k[1] != rate for k in keys[i + 1 :])
            amt = remaining[(t.tax_type, t.rate_pct)] if last else q2(taxable * t.rate_pct / 100)
            remaining[(t.tax_type, t.rate_pct)] -= amt
            total += amt
            taxes.append(
                PrintedTax(t.tax_type, format_rate_pct(t.rate_pct), format_amount(amt, fmt))
            )
        rows.append(PrintedHsn(hsn, format_amount(taxable, fmt), taxes, format_amount(total, fmt)))
    total_row = PrintedHsn(
        "Total",
        format_amount(figures.subtotal, fmt),
        [PrintedTax(t.tax_type, "", format_amount(t.amount, fmt)) for t in figures.taxes],
        format_amount(figures.tax_total(), fmt),
    )
    return rows, total_row


def build_printed(
    spec: DocSpec, figures: Figures, world: World, caps: Caps, rupee_ok: bool
) -> PrintedInvoice:
    style = spec.style
    fmt = style.amounts
    mark = resolve_mark(style, rupee_ok)
    lines = [
        PrintedLine(
            sl=str(i + 1),
            description=ln.desc,
            item_code=ln.code if caps.item_code else None,
            hsn_sac=ln.hsn,
            quantity=str(ln.qty),
            uom=ln.uom,
            unit_price=format_amount(ln.rate, fmt),
            amount=format_amount(lf.amount, fmt),
            tax_rate=format_rate_pct(ln.tax_rate) if caps.line_tax_rate else None,
        )
        for i, (ln, lf) in enumerate(zip(spec.lines, figures.lines, strict=True))
    ]
    taxes = [
        PrintedTax(t.tax_type, format_rate_pct(t.rate_pct), format_amount(t.amount, fmt))
        for t in figures.taxes
    ]
    if style.total_suffix and figures.total == figures.total.to_integral_value():
        total_value = format_amount(figures.total, fmt, dp=0) + style.total_suffix
    else:
        total_value = format_amount(figures.total, fmt)
    inclusive_note = None
    if spec.prices_include_tax:
        sep = "" if mark == RUPEE_SIGN else " "
        parts = [f"{t.tax_type} {t.rate} {mark}{sep}{t.amount}" for t in taxes]
        inclusive_note = "Includes " + " and ".join(parts)
    hsn_rows, hsn_total = _hsn_rows(spec, figures, fmt)
    company = world.company
    vendor = world.vendors.get(spec.supplier.vendor_id or "")
    state = world.states
    return PrintedInvoice(
        doc_id=spec.id,
        title=spec.title,
        number=spec.number,
        date=spec.date_text,
        po_label=style.po_label,
        po_ref=spec.po_ref,
        supplier_name=spec.supplier.legal_name,
        supplier_address_lines=split_address(spec.supplier.address),
        supplier_gstin=spec.supplier.gstin,
        supplier_pan=spec.supplier.gstin[2:12],
        supplier_state=f"{state[spec.supplier.state_code]} ({spec.supplier.state_code})",
        supplier_phone=spec.phone,
        supplier_email=spec.supplier_email,
        buyer_name=company.name,
        buyer_address_lines=split_address(company.address),
        buyer_gstin=company.gstin,
        buyer_state=f"{state[company.state_code]} ({company.state_code})",
        place_of_supply=f"{state[company.state_code]} ({company.state_code})",
        currency_mark=mark,
        lines=lines,
        subtotal=None if spec.prices_include_tax else format_amount(figures.subtotal, fmt),
        taxes=taxes,
        round_off=format_signed(figures.round_off) if figures.round_off else None,
        total=f"{mark} {total_value}",
        total_value=total_value,
        amount_in_words=amount_in_words(figures.total),
        prices_include_tax=spec.prices_include_tax,
        inclusive_note=inclusive_note,
        bank_name=spec.bank.bank_name,
        bank_account_name=spec.supplier.legal_name,
        bank_account=spec.bank.account,
        bank_ifsc=spec.bank.ifsc,
        notes=spec.notes,
        notices=spec.notices,
        tagline=style.tagline,
        accent=style.accent,
        payment_terms_days=vendor.payment_terms_days if vendor else None,
        hsn_rows=hsn_rows,
        hsn_total=hsn_total,
    )


# --- Ground truth -------------------------------------------------------------------------------


def raw_invoice(spec: DocSpec, p: PrintedInvoice) -> RawInvoice:
    """The RawInvoice a perfect reader would return: strings exactly as printed."""
    doc_type = DocType.proforma_invoice if "PROFORMA" in p.title.upper() else DocType.tax_invoice
    annotations = [*p.notices, *p.notes]
    if spec.scan:
        annotations += [m.text for m in (*spec.scan.stamps, *spec.scan.handwriting)]
    tax_lines = [RawTaxLine(tax_type=t.tax_type, rate=t.rate, amount=t.amount) for t in p.taxes]  # type: ignore[arg-type]
    return RawInvoice(
        document_type=doc_type,
        document_title=p.title,
        invoice_number=p.number,
        invoice_date=p.date,
        due_date=None,
        supplier_name=p.supplier_name,
        supplier_gstin=p.supplier_gstin,
        supplier_address=p.supplier_address,
        supplier_phone=p.supplier_phone,
        supplier_email=p.supplier_email,
        buyer_name=p.buyer_name,
        buyer_gstin=p.buyer_gstin,
        place_of_supply=p.place_of_supply,
        po_reference=p.po_ref,
        currency=p.currency_mark,
        line_items=[
            RawLine(
                description=ln.description,
                item_code=ln.item_code,
                hsn_sac=ln.hsn_sac,
                quantity=ln.quantity,
                uom=ln.uom,
                unit_price=ln.unit_price,
                amount=ln.amount,
                tax_rate=ln.tax_rate,
            )
            for ln in p.lines
        ],
        subtotal=p.subtotal,
        tax_lines=tax_lines,
        other_charges=[],
        round_off=p.round_off,
        total=p.total,
        amount_in_words=p.amount_in_words,
        prices_include_tax=p.prices_include_tax,
        bank_account_name=p.bank_account_name,
        bank_account_number=p.bank_account,
        bank_ifsc=p.bank_ifsc,
        bank_name=p.bank_name,
        annotations=annotations,
        legibility="clear",
    )


def _money(value: Decimal) -> str:
    return f"{q2(value):.2f}"


def expected_values(spec: DocSpec, figures: Figures) -> dict[str, Any]:
    """Normalised values a correct extraction should arrive at."""
    return {
        "vendor_id": spec.supplier.vendor_id,
        "supplier_gstin": spec.supplier.gstin,
        "invoice_number": spec.number,
        "invoice_date": parse_printed_date(spec.date_text, spec.style.date_format).isoformat(),
        "po_number": spec.po_number if spec.po_ref else None,
        "currency": "INR",
        "prices_include_tax": spec.prices_include_tax,
        "tax_kind": "inter" if spec.tax == "IGST" else "intra",
        "subtotal": _money(figures.subtotal),
        "cgst": _money(figures.tax_total("CGST")),
        "sgst": _money(figures.tax_total("SGST")),
        "igst": _money(figures.tax_total("IGST")),
        "total_tax": _money(figures.tax_total()),
        "round_off": _money(figures.round_off),
        "total": _money(figures.total),
        "bank_account_number": spec.bank.account,
        "bank_ifsc": spec.bank.ifsc,
        "lines": [
            {
                "po_line": ln.po_line,
                "item_code": ln.code,
                "quantity": str(ln.qty),
                "uom": ln.uom,
                "unit_price": _money(ln.rate),
                "amount": _money(lf.amount),
                "taxable_amount": _money(lf.taxable),
                "tax_rate_pct": str(ln.tax_rate),
            }
            for ln, lf in zip(spec.lines, figures.lines, strict=True)
        ],
    }
