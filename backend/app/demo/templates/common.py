"""Content helpers shared by templates (labels and summary tables, no drawing)."""

from __future__ import annotations

from app.demo.invoice import PrintedInvoice, PrintedTax


def tax_label(t: PrintedTax) -> str:
    return f"{t.tax_type} @ {t.rate}"


def hsn_summary_rows(
    p: PrintedInvoice, width: float = 519
) -> tuple[list[tuple[str, float, str]], list[list[str]]]:
    """Columns (title, width, align) and rows for an HSN/SAC-wise tax summary."""
    tax_types = [t.tax_type for t in p.hsn_total.taxes]
    rate_w = 56
    fixed = 70 + 90 + 90 + rate_w * len(tax_types)
    amount_w = (width - fixed) / len(tax_types) if tax_types else 0
    cols: list[tuple[str, float, str]] = [("HSN/SAC", 70, "left"), ("Taxable Value", 90, "right")]
    for tt in tax_types:
        cols += [(f"{tt} Rate", rate_w, "right"), (f"{tt} Amount", amount_w, "right")]
    cols.append(("Total Tax Amount", 90, "right"))
    rows: list[list[str]] = []
    for row in [*p.hsn_rows, p.hsn_total]:
        cells = [row.hsn, row.taxable]
        by_type = {t.tax_type: t for t in row.taxes}
        for tt in tax_types:
            t = by_type.get(tt)
            cells += [t.rate if t else "", t.amount if t else ""]
        cells.append(row.total_tax)
        rows.append(cells)
    return cols, rows
