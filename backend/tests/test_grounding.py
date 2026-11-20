from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.enums import ConfidenceLevel, DocKind
from app.extract import confidence
from app.extract.grounding import Grounder, union_bbox
from app.models.extraction import BBox, DocumentRead, PageRead, Word


def _doc(lines: list[str], kind: DocKind = DocKind.digital) -> DocumentRead:
    words: list[Word] = []
    for row, line in enumerate(lines):
        for col, text in enumerate(line.split()):
            x0, y0 = 0.05 + col * 0.1, 0.05 + row * 0.05
            words.append(
                Word(
                    text=text,
                    bbox=BBox(page=0, x0=x0, y0=y0, x1=x0 + 0.08, y1=y0 + 0.02),
                    conf=None,
                )
            )
    page = PageRead(
        index=0, width_pt=595, height_pt=842, kind=kind, text=" ".join(lines), words=words,
        ocr_used=False, ocr_mean_conf=None,
    )  # fmt: skip
    return DocumentRead(
        sha256="0" * 64, pages=[page], doc_kind=kind, ocr_available=False, page_count=1
    )


DOC = _doc(
    [
        "TAX INVOICE",
        "Sharma Packaging Industries",
        "Invoice No.: SPI/26-27/0214",
        "Invoice Date: 12/11/2026",
        "Order Ref: KF PO 0146",
        "Dated 05 Nov 2026",
        "Grand Total Rs. 1,16,348.00",
        "Rupees One Lakh Sixteen Thousand Only",
    ]
)


def test_number_grounding_over_word_windows() -> None:
    g = Grounder(DOC)
    res = g.number(Decimal("116348.00"))
    assert res.status == "exact"
    assert len(res.bbox) == 1 and res.bbox[0].page == 0
    assert g.number(Decimal("999.00")).status == "none"


def test_date_grounding_single_and_multi_word() -> None:
    g = Grounder(DOC)
    assert g.date(date(2026, 11, 12)).status == "exact"
    three = g.date(date(2026, 11, 5))
    assert three.status == "exact"
    box = three.bbox[0]
    assert box.x1 - box.x0 > 0.2  # spans "05 Nov 2026"
    assert g.date(date(2026, 1, 1)).status == "none"


def test_text_grounding_exact_and_fuzzy() -> None:
    g = Grounder(DOC)
    assert g.text("SPI/26-27/0214").status == "exact"
    assert g.text("KF PO 0146").status == "exact"
    assert g.text("Sharma Packaging Industries").status == "exact"
    assert g.text("Sharma Packagng Industries").status == "fuzzy"
    assert g.text("Completely Different Name").status == "none"


def test_grounding_unavailable_without_words() -> None:
    scanned = _doc([], kind=DocKind.scanned)
    g = Grounder(scanned)
    assert g.text("anything").status == "unavailable"
    assert g.number(Decimal("1")).status == "unavailable"
    assert g.date(date(2026, 1, 1)).status == "unavailable"


def test_union_bbox() -> None:
    words = [w for p in DOC.pages for w in p.words][:2]
    (box,) = union_bbox(words)
    assert box.x0 == words[0].bbox.x0 and box.x1 == words[1].bbox.x1


def test_confidence_points() -> None:
    assert confidence.points("exact", True) == 100
    assert confidence.points("exact", False) == 65
    assert confidence.points("fuzzy", True) == 80
    assert confidence.points("none", True) == 55
    assert confidence.points("unavailable", True) == 80
    assert confidence.points("none", False) == 20
    assert confidence.score("unavailable", True) == (0.8, ConfidenceLevel.high)
    assert confidence.score("exact", False) == (0.65, ConfidenceLevel.medium)
    assert confidence.score("fuzzy", False) == (0.45, ConfidenceLevel.low)
    assert confidence.missing() == (0.0, ConfidenceLevel.low)
