"""Invoice numbers printed in the file, found by code from the positioned words of each page.

Two things come out of it:
- `invoices_in_file`: the invoice numbers heading *different pages* when there is more than one,
  i.e. several invoices scanned or merged into one PDF. A two-page invoice repeating its own
  number on page 2 gives one number, so nothing is reported. A single page is never split.
- `referenced_invoices`: numbers printed after "Against / Original / Ref. invoice", as on a
  credit note that names the invoice it adjusts.

Labels are matched on words, not on raw text order, so table layouts work: the value is the next
word with a digit to the right of the label on the same line, or else the word just below it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.extraction import DocumentRead, Word

from .normalize import canonical_invoice_number

_LABEL = re.compile(r"^(?:tax)?(?:invoice|inv|bill)(?:no|number|num|#)?$")
_NUMBER_WORDS = ("no", "number", "num", "#")
_REF_WORDS = ("against", "original", "ref", "reference")
_NOT_INVOICE_WORDS = {"eway", "way", "e"}  # "e-Way Bill No." is a transport document number
_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-.]{1,28}$")


@dataclass(frozen=True)
class PrintedNumber:
    page: int
    number: str
    reference: bool


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9#]", "", text.lower())


def _lines(words: list[Word]) -> list[list[Word]]:
    """Group words into text lines by vertical overlap, each sorted left to right."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.bbox.y0, w.bbox.x0)):
        mid = (w.bbox.y0 + w.bbox.y1) / 2
        for line in lines:
            ref = line[0].bbox
            if ref.y0 <= mid <= ref.y1:
                line.append(w)
                break
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.bbox.x0) for line in lines]


def _is_value(text: str) -> bool:
    clean = text.strip(":;,")
    return bool(_VALUE.match(clean)) and any(ch.isdigit() for ch in clean)


def _label_end(line: list[Word], i: int) -> tuple[int, bool] | None:
    """If an invoice-number label ("Invoice No.", "Tax Invoice #", "Bill No:", or a bare
    "Invoice" for references) starts at word i: (index after it, whether it names a number)."""
    joined, found = "", None
    for j in range(i, min(i + 3, len(line))):
        joined += _norm(line[j].text)
        if _LABEL.match(joined):
            found = (j + 1, joined.endswith(_NUMBER_WORDS))
    return found


def _value_after(line: list[Word], start: int) -> str | None:
    for w in line[start : start + 3]:
        if _is_value(w.text):
            return w.text.strip(":;,")
    return None


def _value_below(lines: list[list[Word]], li: int, label: Word) -> str | None:
    if li + 1 >= len(lines):
        return None
    for w in lines[li + 1]:
        if w.bbox.x1 >= label.bbox.x0 and w.bbox.x0 <= label.bbox.x1 + 0.05 and _is_value(w.text):
            return w.text.strip(":;,")
    return None


def printed_numbers(doc: DocumentRead) -> list[PrintedNumber]:
    out: list[PrintedNumber] = []
    for page in doc.pages:
        lines = _lines(page.words)
        for li, line in enumerate(lines):
            for i in range(len(line)):
                found = _label_end(line, i)
                if found is None:
                    continue
                end, has_number_word = found
                before = {_norm(w.text).rstrip(":") for w in line[max(0, i - 2) : i]}
                if before & _NOT_INVOICE_WORDS:
                    continue
                reference = bool(before & set(_REF_WORDS))
                if not (has_number_word or reference):
                    continue  # a bare "Invoice" heading is not a label
                value = _value_after(line, end) or _value_below(lines, li, line[i])
                if value is not None:
                    out.append(PrintedNumber(page.index, value, reference))
    return out


def invoices_in_file(numbers: list[PrintedNumber]) -> list[str]:
    """Distinct invoice numbers heading different pages; empty unless there are two or more."""
    first_per_page: dict[int, str] = {}
    for n in numbers:
        if not n.reference:
            first_per_page.setdefault(n.page, n.number)
    seen: dict[str, str] = {}
    for _, number in sorted(first_per_page.items()):
        key = canonical_invoice_number(number) or number
        seen.setdefault(key, number)
    return list(seen.values()) if len(seen) > 1 else []


def referenced_invoices(numbers: list[PrintedNumber]) -> list[str]:
    seen: dict[str, str] = {}
    for n in numbers:
        if n.reference:
            seen.setdefault(canonical_invoice_number(n.number) or n.number, n.number)
    return list(seen.values())
