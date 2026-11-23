# Robustness: ten unseen invoices

The fifteen demo scenarios are drawn with four templates. To see how the process copes with
documents it has never seen, `backend/app/demo/unseen.py` generates ten deliberately different
files (U01–U10) with their own layouts, plus ground truth and an expected outcome. They are
written to `DATA_DIR/demo/unseen/` with the demo world, listed in the demo inbox as the
**stress** group, and can be run with `POST /api/demo/runs/U01` … `U10`.

The bar for each: never crash; read what can be read; end in a sensible Hold, Return or Reject
with a specific explanation. None of them can auto-approve against a PO used by the demo
scenarios, so running them never changes S01–S15.

## Results (live)

Run on 21 Nov 2026 with `gemini-3.5-flash-lite`, fresh readings, Tesseract on, each document
from a freshly seeded database. All ten end where expected; the offline test suite checks the
same outcomes with the ground-truth reader (`backend/tests/test_robustness.py`). The pack is also
part of the evaluation: `make eval-stress-live` gives 10 / 10 decisions and 249 / 249 fields read
correctly (`make eval-stress` is the offline gate); see [EVAL.md](EVAL.md).

| Doc | What's unusual | Outcome | Reason | What the system did |
|---|---|---|---|---|
| U01 | Two pages, 28 lines; totals, tax and bank details only on page 2 | Hold · buyer | PO not found ("0161" doesn't exist) | Read all 28 lines and the page-2 totals; line, subtotal and GST arithmetic all reconcile. Page 2 repeats the invoice number and is correctly *not* taken for a second invoice. Reading took 10 s (28 lines of output). |
| U02 | Image-only scan fed in sideways (rotated 90°) | Hold · buyer | No PO for this invoice | Every field read correctly. **Fixed:** OCR used to read the sideways text as junk, so every field failed grounding and the run also asked for a field check. OCR now detects the orientation, reads the page upright and maps word boxes back onto the page as shown. |
| U03 | 110 dpi phone photo, perspective skew, uneven light, shadow, desk background | Hold · AP clerk | Some key fields need a second look; PO inferred (KF-PO-0149) | Every value read correctly, but the invoice number and total can't be confirmed on the photo by OCR, so a clerk is asked to check them. The best-fit PO is the October storage PO, offered for confirmation rather than assumed. Reasonable: the photo is the weakest input in the pack. |
| U04 | Local repair shop's bill: no heading, no GSTIN for either party, no GST, no quantities | Hold · procurement | Vendor not in the vendor master | **Fixed twice.** The model filed the bill as "other" (it has no heading), which rejected it as "not an invoice"; a document with a bill number and a total is now checked as a bill. It was also returned to the vendor for a GSTIN it can't have; with no GST charged, the GSTIN checks are now skipped. |
| U05 | US vendor, USD, Letter paper, month-first dates, no GST, SWIFT instead of IFSC | Hold · procurement | Vendor not in the vendor master; invoice in USD | **Fixed.** "USD 5,212.50" used to fail to parse (so the run was returned for a missing total) and the GSTIN checks returned it as well. Foreign amounts now parse, the currency is flagged even without a PO, every amount in the explanation is written as USD (never ₹), and the foreign bank account is validated without an IFSC. |
| U06 | Credit note quoting invoice SPI/26-27/0198 | Hold · AP clerk | Document is a credit note | **Fixed.** It used to be matched against an inferred PO and given a generic "can this go ahead?". PO and line matching are now skipped for credit and debit notes, and the question names the original invoice found in the ledger (R-0014, approved) and says to book the ₹1,817.00 against the vendor's account instead of paying it. |
| U07 | GST e-invoice: IRN, acknowledgement number and date, e-way bill number, QR block | Hold · buyer | No PO for this invoice | The model took the invoice number, not the IRN, Ack No or e-way bill number. The page scanner ignores "e-Way Bill No." as an invoice label. |
| U08 | Negative trade-discount line in the item table; GST on the discounted value; TCS 0.1% on top | Hold · buyer | PO not found ("KF-PO-0163" doesn't exist) | Discount line read as −₹1,925.00 and TCS as a separate tax line; subtotal, GST, TCS, round-off and total all reconcile, so no arithmetic findings. |
| U09 | Two one-page invoices (RSE/0466, RSE/0467) merged into one PDF | Hold · AP clerk | File contains 2 invoices | **Fixed.** It used to be read as one invoice and held only for its PO. Code now finds the invoice number heading each page; two different numbers stop the checks and ask the clerk to split the file. |
| U10 | Delivery challan: quantities only, no prices, no tax | Reject | Not an invoice | **Improved.** Field checks are now skipped for a non-invoice (it was also reported as "no total printed"), and the explanation says it is a delivery challan for KF-PO-0142, that there is nothing to pay, and that receiving can use it to record the goods receipt. |

Field accuracy (live): every value the model returned matched the printed truth after the
code's normalisation. It copied "Rs." where the truth says "INR" and dropped the currency mark
from two totals; the parsed amounts and currencies were still right. On U10 it rightly did not
use the challan number as an invoice number.

Timing (live, local): 2.7 to 6 s per document end to end, except U01 at 11.4 s (28 lines to
transcribe). Under the free tier's 15 requests per minute, running all ten back to back hit the
limit once (U10); the run failed cleanly with "The model provider is busy (rate limited)" and
passed on a re-run.

## What changed in the code

- `extract/invoice_refs.py`: finds "Invoice No." labels on each page's positioned words (value to
  the right or below); stores `invoices_in_file` and `referenced_invoices` on the extraction.
- New check D09 and reason code `DOC_MULTIPLE_INVOICES` (stops the later checks).
- Credit and debit notes skip `resolve_po` and `match_lines`; new handoff templates for credit
  notes, non-invoices, merged files and foreign currency.
- T01/T02 skip when no GSTIN is printed and no GST is charged; P05 flags a non-INR invoice even
  without a PO; amounts in messages follow the invoice's currency.
- Amount parsing and currency detection understand USD, US$, $, EUR, €, GBP, £.
- D01 checks a document filed as "other" as a bill when it has a bill number or a bill title and
  a total; D02–D09 are skipped for a non-invoice.
- OCR: orientation detection on landscape or weak pages, then a second pass on the upright image.

## Limits

These are synthetic documents built to exercise one difference each. A real photo can be far
worse than U03, and only the e-invoice's printed fields are read: the QR code isn't decoded or
checked against the IRN. A single page holding two invoices side by side is not detected.
