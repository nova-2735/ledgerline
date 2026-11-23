# Evaluation results

**Date:** 2026-11-21 · **Model:** `gemini-3.5-flash-lite` (Gemini API) · **Policy:** `2026-11-20.1+c69c9db3`
**Commands:** `make eval-live` (the 15 scenarios) and `make eval-stress-live` (the 10 unseen
documents), both with fresh model readings (cache bypassed), each document starting from a
freshly seeded database, explanation polish off so only the reading uses the model. Tesseract on.

## Headline

| | 15 demo scenarios | 10 unseen documents |
|---|---|---|
| Decisions correct (scenarios include the after-review outcomes of S04 and S06) | **15 / 15** | **10 / 10** |
| Invoice fields read correctly | **237 / 237** | **249 / 249** |
| — digital documents | 204 / 204 (13 invoices) | 216 / 216 (8 documents) |
| — scanned documents | 33 / 33 (S04, S05) | 33 / 33 (sideways scan, phone photo) |
| Model reading time per document | p50 2.1 s · p95 3.3 s · max 4.5 s | p50 2.0 s · p95 6.9 s · max 7.1 s |
| Whole pipeline per document (all 11 steps, local) | p50 2.2 s · p95 3.7 s · max 4.6 s | p50 2.0 s · p95 7.5 s · max 7.7 s |
| Tokens | 19,185 in · 9,922 out | 13,842 in · 8,936 out |
| Rate limiting (429) or retries | none | none |

The slow tail of the unseen set is U01 (28 line items to transcribe, 7.1 s) and the phone photo
U03 (6.7 s). The offline baselines (`make eval`, `make eval-stress`, ground-truth reader) are
also 15 / 15 and 10 / 10 with every field correct; both exit non-zero on any wrong decision and
gate changes to the rules and policy.

Fields compared: invoice number, date, supplier and buyer GSTIN, PO reference, subtotal, CGST,
SGST, IGST, total, bank account, IFSC, and each line's quantity, unit price and amount — after the
code's own normalisation, so "1,16,348/-" and "116348.00" count as the same value. For the unseen
documents the truth is the printed strings, read through the same normalisation.

## The unseen documents

Ten deliberately different files: a two-page invoice, a sideways scan, a phone photo, an
unregistered trader's bill, a USD invoice, a credit note, an e-invoice, a discount-and-TCS
invoice, two invoices in one PDF and a delivery challan. Before the fixes in this round, three
of them ended wrongly even with a perfect reading (the trader's bill and the USD invoice were
returned for a GSTIN they can't have, and the merged file was treated as one invoice), the USD
total couldn't be parsed and the sideways scan failed field grounding; all ten now end in the
expected Hold or Reject. The
per-document table, with what the system did right or wrong, is in
[ROBUSTNESS.md](ROBUSTNESS.md).

## Latency on the deployed instance

The free Render instance has 0.1 vCPU, so CPU work there is many times slower than locally.
Measured on a local server capped at 0.1 vCPU (method and full tables in
[PERFORMANCE.md](PERFORMANCE.md)):

| | Before this round | After |
|---|---|---|
| First live run after start (S06), wall | 14.1 s | 4.1 s |
| Scanned invoice (S04), wall | 52.1 s | 18.6 s |
| Demo reset | 79.4 s | 0.4 to 0.7 s |

Measured on the deployed service (`make smoke`, version 0.2.0, fresh readings, 23 Nov 2026):

| | Before | After |
|---|---|---|
| Demo reset | about 87 s | 0.4 s (0.1 s on the server) |
| S01 (digital, approve), run | — | 4.1 to 9.2 s, mostly the two model calls |
| S06 (digital, hold), run | about 19 s end to end | 4.2 to 5.5 s |
| S04 (scan), run | — | 11.4 s, of which OCR 7.9 s (43.4 s before OCR was made single-threaded) |

Details in [PERFORMANCE.md](PERFORMANCE.md).

## What failed and why

Nothing in the final runs. Earlier problems, all fixed with regression tests:

1. **Dates in stored readings came back as the letter "f"** (a serializer applied to the wrong
   type in a union), breaking anything that re-read a stored run.
2. **Tax-inclusive invoice (S08) scored a false miss on "subtotal"**: the truth for subtotal,
   buyer GSTIN and PO reference is now what is printed on the page.
3. **The unseen documents** exposed the gaps listed in [ROBUSTNESS.md](ROBUSTNESS.md). One
   live-only case: the model filed the trader's bill (no heading) as "other", which rejected it
   as not an invoice; a document with a bill number and a total is now checked as a bill.

## Caveats

All documents are synthetic and generated from one seeded world; the scans and the photo are
simulated. Twenty-five documents show that the pipeline and policy behave as designed on each
kind of input, not a production accuracy rate. Raw reports (`reports/eval_*.md`, `.json`) are
regenerated on demand and kept out of git.
