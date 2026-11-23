"""Audit record of one run as a PDF: a one-page summary, then the checks, the extracted fields,
the stage timeline, review actions and decision history.

Amounts use a font with the ₹ glyph when one is installed (DejaVu Sans in the container,
`INVOICE_FONT_PATH`); otherwise they are written "Rs." in Helvetica.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app import clock
from app.demo.templates.base import rupee_font
from app.enums import CheckStatus, StageName
from app.models.extraction import FieldValue, InvoiceExtraction
from app.models.run import RunDetail, RunEvent
from app.rules.base import inr, money_currency

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#616e7c")
RULE = colors.HexColor("#d3d9e0")
HEAD_BG = colors.HexColor("#eef1f5")
OUTCOME_COLOURS = {
    "APPROVE": colors.HexColor("#1e7b46"),
    "HOLD": colors.HexColor("#a35d00"),
    "RETURN": colors.HexColor("#1d5fa8"),
    "REJECT": colors.HexColor("#b42318"),
}
STATUS_COLOURS = {
    CheckStatus.pass_: colors.HexColor("#1e7b46"),
    CheckStatus.warn: colors.HexColor("#a35d00"),
    CheckStatus.fail: colors.HexColor("#b42318"),
    CheckStatus.skip: MUTED,
}
FIELD_LABELS = {
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "due_date": "Due date",
    "supplier_name": "Supplier",
    "supplier_gstin": "Supplier GSTIN",
    "supplier_phone": "Supplier phone",
    "buyer_name": "Buyer",
    "buyer_gstin": "Buyer GSTIN",
    "place_of_supply": "Place of supply",
    "po_reference": "PO reference",
    "subtotal": "Subtotal",
    "round_off": "Round-off",
    "total": "Total",
    "amount_in_words": "Amount in words",
    "bank_account_number": "Bank account",
    "bank_ifsc": "IFSC",
    "bank_name": "Bank",
}
STAGE_LABELS = {
    StageName.intake: "Receive file",
    StageName.read_document: "Read document",
    StageName.extract_fields: "Read invoice fields",
    StageName.validate_document: "Check document",
    StageName.identify_vendor: "Identify vendor",
    StageName.check_tax: "Check GST",
    StageName.resolve_po: "Find purchase order",
    StageName.match_lines: "Match lines",
    StageName.check_duplicates: "Check duplicates",
    StageName.decide: "Decide",
    StageName.explain_route: "Explain and route",
}


@lru_cache
def _fonts() -> tuple[str, str, bool]:
    """(regular, bold, has ₹ glyph)."""
    path = rupee_font()
    if path is None:
        return "Helvetica", "Helvetica-Bold", False
    regular = "AuditSans"
    if regular not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular, str(path)))
    bold_path = _bold_sibling(path)
    bold = regular
    if bold_path is not None:
        bold = "AuditSans-Bold"
        if bold not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(bold, str(bold_path)))
    return regular, bold, True


def _bold_sibling(path: Path) -> Path | None:
    for name in (path.stem + "-Bold" + path.suffix, path.stem + "bd" + path.suffix):
        candidate = path.with_name(name)
        if candidate.is_file():
            return candidate
    return None


class _Styles:
    def __init__(self) -> None:
        regular, bold, self.rupee = _fonts()
        base = {"fontName": regular, "textColor": INK, "alignment": TA_LEFT}
        self.title = ParagraphStyle("title", fontName=bold, fontSize=16, leading=20, textColor=INK)
        self.h2 = ParagraphStyle(
            "h2",
            fontName=bold,
            fontSize=11.5,
            leading=15,
            spaceBefore=10,
            spaceAfter=4,
            textColor=INK,
        )
        self.body = ParagraphStyle("body", fontSize=9.5, leading=13, **base)
        self.small = ParagraphStyle("small", fontSize=8, leading=10.5, **base)
        self.muted = ParagraphStyle(
            "muted", fontSize=8, leading=10.5, fontName=regular, textColor=MUTED
        )
        self.cell = ParagraphStyle("cell", fontSize=7.8, leading=9.6, **base)
        self.cell_bold = ParagraphStyle(
            "cellb", fontSize=7.8, leading=9.6, fontName=bold, textColor=INK
        )
        self.bold = bold

    def text(self, value: Any) -> str:
        s = escape("" if value is None else str(value))
        return s if self.rupee else s.replace("₹", "Rs. ")


def _ist(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(clock.IST).strftime("%d %b %Y, %H:%M:%S IST")


def _money(value: Decimal | None) -> str:
    return inr(value) if value is not None else "—"


def _field_value(fv: FieldValue) -> str:
    v = fv.value
    if v is None:
        return "—"
    if isinstance(v, Decimal):
        return _money(v)
    if hasattr(v, "strftime"):
        return f"{v:%d %b %Y}"
    return str(v)


def _table(
    rows: list[list[Any]],
    widths: list[float],
    header: bool = True,
    extra: list[tuple[Any, ...]] | None = None,
) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), HEAD_BG))
    t.setStyle(TableStyle(style + (extra or [])))
    return t


class AuditPDF:
    def __init__(self, run: RunDetail, events: list[RunEvent]) -> None:
        self.run = run
        self.events = events
        self.s = _Styles()
        self.width = A4[0] - 30 * mm

    def p(self, value: Any, style: ParagraphStyle | None = None) -> Paragraph:
        return Paragraph(self.s.text(value), style or self.s.cell)

    # --- page 1 ------------------------------------------------------------------------------

    def summary(self) -> list[Any]:
        run, s = self.run, self.s
        d = run.decision
        outcome = (d.outcome.value if d else None) or "NO DECISION"
        colour = OUTCOME_COLOURS.get(outcome, MUTED)
        story: list[Any] = [
            Paragraph(f"Audit record · {s.text(run.display_id)}", s.title),
            Paragraph(
                s.text(
                    f"{run.filename} · received {_ist(run.created_at)} · source {run.source.value}"
                    f" · status {run.status.value.replace('_', ' ')}"
                ),
                s.muted,
            ),
            Spacer(1, 8),
        ]
        badge = Table(
            [
                [
                    Paragraph(f'<font color="white">{s.text(outcome)}</font>', s.title),
                    Paragraph(s.text(d.headline if d else "The run has no decision."), s.body),
                ]
            ],
            colWidths=[38 * mm, self.width - 38 * mm],
        )
        badge.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), colour),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BOX", (0, 0), (-1, -1), 0.6, colour),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(badge)
        story.append(Spacer(1, 8))
        handoff = d.handoff if d else None
        at_risk = handoff.amount_at_risk if handoff else None
        facts = [
            ("Vendor", run.vendor_name or (run.vendor_id or "not in the vendor master")),
            ("Invoice number", run.invoice_number or "—"),
            ("Invoice date", f"{run.invoice_date:%d %b %Y}" if run.invoice_date else "—"),
            ("Total", _money(run.total)),
            ("Purchase order", run.po_number or "—"),
            ("Amount at risk", _money(at_risk)),
            ("Route", (d.route.value.replace("_", " ") if d else "—")),
            ("Final outcome", run.final_outcome.value if run.final_outcome else "not final yet"),
            ("Decided", _ist(d.decided_at) if d else "—"),
            ("Policy version", run.policy_version or "—"),
        ]
        half = (len(facts) + 1) // 2
        rows = []
        for i in range(half):
            left = facts[i]
            right = facts[i + half] if i + half < len(facts) else ("", "")
            rows.append(
                [
                    self.p(left[0], s.cell_bold),
                    self.p(left[1]),
                    self.p(right[0], s.cell_bold),
                    self.p(right[1]),
                ]
            )
        w = self.width
        story.append(_table(rows, [w * 0.17, w * 0.33, w * 0.17, w * 0.33], header=False))
        if handoff is not None:
            story += [
                Paragraph("Next step", s.h2),
                Paragraph(s.text(f"Owner: {handoff.owner.value.replace('_', ' ')}"), s.body),
                Paragraph(s.text(f"Question: {handoff.question}"), s.body),
                Paragraph(s.text(f"Suggested action: {handoff.suggested_action}"), s.body),
            ]
        if d is not None:
            story += [Paragraph("Summary", s.h2), Paragraph(s.text(d.explanation.summary), s.body)]
            if d.explanation.bullets:
                story.append(Spacer(1, 4))
                for b in d.explanation.bullets[:8]:
                    story.append(Paragraph(s.text(f"• {b}"), s.small))
            by = "the template" if d.explanation.generated_by == "template" else "the model"
            story.append(Spacer(1, 4))
            story.append(Paragraph(s.text(f"Summary written by {by}."), s.muted))
        if d is not None and d.posting is not None:
            story.append(Paragraph("Posting", s.h2))
            rows = [
                [
                    self.p(h, s.cell_bold)
                    for h in ("PO line", "GL", "Cost centre", "Taxable", "Tax", "Description")
                ]
            ]
            for ln in d.posting.lines:
                rows.append(
                    [
                        self.p(ln.po_line_no if ln.po_line_no is not None else "—"),
                        self.p(ln.gl_account),
                        self.p(ln.cost_center),
                        self.p(_money(ln.taxable_amount)),
                        self.p(_money(ln.tax_amount)),
                        self.p(ln.description),
                    ]
                )
            story.append(_table(rows, [w * x for x in (0.09, 0.1, 0.14, 0.14, 0.12, 0.41)]))
        return story

    # --- detail pages ------------------------------------------------------------------------

    def checks(self) -> list[Any]:
        s, w = self.s, self.width
        rows = [[self.p(h, s.cell_bold) for h in ("Stage", "Rule", "Result", "Finding")]]
        extra: list[tuple[Any, ...]] = []
        for i, c in enumerate(self.run.checks, start=1):
            status = c.status.value + (" (resolved)" if c.resolved_by_review else "")
            finding = f"<b>{s.text(c.title)}</b><br/>{s.text(c.message)}"
            if c.code is not None:
                finding += f"<br/><font color='#616e7c'>{s.text(c.code.value)}</font>"
            rows.append(
                [
                    self.p(STAGE_LABELS.get(c.stage, c.stage.value)),
                    self.p(c.rule_id),
                    self.p(status),
                    Paragraph(finding, s.cell),
                ]
            )
            extra.append(("TEXTCOLOR", (2, i), (2, i), STATUS_COLOURS.get(c.status, INK)))
        return [
            Paragraph(f"Checks ({len(self.run.checks)})", s.h2),
            _table(rows, [w * 0.16, w * 0.2, w * 0.1, w * 0.54], extra=extra),
        ]

    def fields(self) -> list[Any]:
        s, w = self.s, self.width
        ex: InvoiceExtraction | None = self.run.extraction
        if ex is None:
            return [Paragraph("Extracted fields", s.h2), self.p("No extraction.", s.body)]
        rows = [
            [
                self.p(h, s.cell_bold)
                for h in ("Field", "Value", "As printed", "Confidence", "Located on page")
            ]
        ]
        for name, label in FIELD_LABELS.items():
            fv = getattr(ex, name)
            if fv.raw is None and fv.value is None:
                continue
            located = {
                "exact": "yes",
                "fuzzy": "approximately",
                "none": "no",
                "unavailable": "no text layer",
            }[fv.grounded]
            rows.append(
                [
                    self.p(label),
                    self.p(_field_value(fv)),
                    self.p(fv.raw or "—"),
                    self.p(f"{round(fv.confidence * 100)}% ({fv.level.value})"),
                    self.p(located),
                ]
            )
        story: list[Any] = [
            Paragraph("Extracted fields", s.h2),
            _table(rows, [w * 0.17, w * 0.23, w * 0.3, w * 0.14, w * 0.16]),
        ]
        if ex.line_items:
            lines = [
                [
                    self.p(h, s.cell_bold)
                    for h in ("#", "Description", "Qty", "Unit price", "Amount", "GST %")
                ]
            ]
            for ln in ex.line_items:
                lines.append(
                    [
                        self.p(ln.index + 1),
                        self.p(ln.description),
                        self.p(
                            f"{ln.quantity.normalize():f} {ln.uom or ''}".strip()
                            if ln.quantity is not None
                            else "—"
                        ),
                        self.p(_money(ln.unit_price)),
                        self.p(_money(ln.amount)),
                        self.p(
                            f"{ln.tax_rate_pct.normalize():f}"
                            if ln.tax_rate_pct is not None
                            else "—"
                        ),
                    ]
                )
            story += [
                Spacer(1, 6),
                Paragraph(f"Line items ({len(ex.line_items)})", s.h2),
                _table(lines, [w * x for x in (0.05, 0.45, 0.12, 0.14, 0.14, 0.1)]),
            ]
        meta = ex.meta
        cached = " (saved reading)" if meta.cached else ""
        story.append(Spacer(1, 4))
        story.append(
            self.p(
                f"Read by {meta.provider} · {meta.model} · prompt {meta.prompt_id}@"
                f"{meta.prompt_version} · {meta.latency_ms} ms{cached}",
                s.muted,
            )
        )
        return story

    def timeline(self) -> list[Any]:
        s, w = self.s, self.width
        rows = [[self.p(h, s.cell_bold) for h in ("Stage", "Status", "Started", "Took", "Summary")]]
        for st in self.run.stages:
            took = f"{st.duration_ms:,} ms" if st.duration_ms is not None else "—"
            rows.append(
                [
                    self.p(STAGE_LABELS.get(st.name, st.name.value)),
                    self.p(st.status.value),
                    self.p(_ist(st.started_at)),
                    self.p(took),
                    self.p(st.summary or ""),
                ]
            )
        total = self.run.duration_ms
        story: list[Any] = [
            Paragraph("Stage timeline", s.h2),
            _table(rows, [w * 0.16, w * 0.09, w * 0.22, w * 0.09, w * 0.44]),
        ]
        if total is not None:
            story.append(self.p(f"Whole run: {total:,} ms.", s.muted))
        calls = [
            (e.data or {}).get("llm_call")
            for e in self.events
            if e.type == "stage.log" and (e.data or {}).get("llm_call")
        ]
        if calls:
            story.append(Spacer(1, 4))
            for call in calls:
                assert call is not None
                story.append(
                    self.p(
                        f"Model call · {call.get('kind')} · {call.get('provider')} · "
                        f"{call.get('model')} · {call.get('prompt')} · "
                        f"{call.get('latency_ms')} ms"
                        + (" · cached" if call.get("cached") else ""),
                        s.muted,
                    )
                )
        return story

    def reviews(self) -> list[Any]:
        s, w = self.s, self.width
        story: list[Any] = [Paragraph("Review actions", s.h2)]
        if not self.run.review_actions:
            story.append(self.p("None.", s.body))
        else:
            rows = [
                [self.p(h, s.cell_bold) for h in ("When", "Reviewer", "Action", "Note", "Decision")]
            ]
            for a in self.run.review_actions:
                version = a.resulting_decision_version
                rows.append(
                    [
                        self.p(_ist(a.created_at)),
                        self.p(a.reviewer),
                        self.p(a.action.value.replace("_", " ")),
                        self.p(a.note),
                        self.p(f"v{version}" if version else "—"),
                    ]
                )
            story.append(_table(rows, [w * 0.22, w * 0.18, w * 0.13, w * 0.37, w * 0.1]))
        if self.run.decision_history:
            rows = [
                [
                    self.p(h, s.cell_bold)
                    for h in ("Version", "Outcome", "Route", "Decided", "Policy")
                ]
            ]
            for d in self.run.decision_history:
                rows.append(
                    [
                        self.p(f"v{d.version}"),
                        self.p(d.outcome.value),
                        self.p(d.route.value.replace("_", " ")),
                        self.p(_ist(d.decided_at)),
                        self.p(d.policy_version),
                    ]
                )
            story += [
                Paragraph("Decision history", s.h2),
                _table(rows, [w * 0.1, w * 0.14, w * 0.16, w * 0.26, w * 0.34]),
            ]
        return story

    # --- document ----------------------------------------------------------------------------

    def _footer(self, canvas: Canvas, doc: Any) -> None:
        regular = _fonts()[0]
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(MUTED)
        text = (
            f"Ledgerline audit record · {self.run.display_id} · file sha256 "
            f"{self.run.file_sha256[:16]}… · page {doc.page}"
        )
        canvas.drawString(15 * mm, 10 * mm, text)
        canvas.restoreState()

    def build(self) -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=14 * mm,
            bottomMargin=16 * mm,
            title=f"Audit record {self.run.display_id}",
            author="Ledgerline",
            subject=f"Run {self.run.display_id}",
        )
        story = [
            *self.summary(),
            PageBreak(),
            *self.checks(),
            *self.fields(),
            KeepTogether(self.timeline()),
            *self.reviews(),
        ]
        doc.build(story, onFirstPage=self._footer, onLaterPages=self._footer)
        return buf.getvalue()


def audit_pdf(run: RunDetail, events: list[RunEvent]) -> bytes:
    """The run's audit record as PDF bytes (amounts in the invoice's currency)."""
    currency = run.extraction.currency if run.extraction is not None else "INR"
    with money_currency(currency):
        return AuditPDF(run, events).build()
