# Evaluation results

**Date:** 2026-11-20 · **Model:** `gemini-3.5-flash-lite` (Gemini API) · **Policy:** `2026-11-20.1+c69c9db3`
**Command:** `make eval-live` (fresh model readings, cache bypassed; each scenario starts from a
freshly seeded database; explanation polish off so only the reading uses the model)

## Headline

| | Result |
|---|---|
| Decisions correct (S01–S15, incl. after-review outcomes for S04 and S06) | **15 / 15** |
| Invoice fields read correctly (237 fields across 15 invoices) | **237 / 237 (100%)** |
| — digital invoices (13) | 204 / 204 |
| — scanned invoices (S04, S05) | 33 / 33 |
| Model reading time per invoice | p50 2.8 s · p95 3.7 s · max 3.7 s |
| Whole pipeline per invoice (all 11 steps) | p50 3.1 s · max 4.7 s |
| Tokens for the 15 readings | 19,185 in · 9,939 out |
| Rate limiting (429) or retries | none |

The offline baseline (`make eval`, ground-truth reader) is also 15 / 15 with 237 / 237 fields; it
exits non-zero on any wrong decision, so it is the gate for changes to the rules and policy.

Fields compared: invoice number, date, supplier and buyer GSTIN, PO reference, subtotal, CGST,
SGST, IGST, total, bank account, IFSC, and each line's quantity, unit price and amount — after the
code's own normalisation, so "1,16,348/-" and "116348.00" count as the same value.

## What failed and why

Nothing in the final run. Two problems were found and fixed while building the pipeline and the
harness:

1. **Dates in stored readings came back as the letter "f".** Inside the `str | Decimal | date`
   field type, the JSON serializer for decimals was applied to dates. Fresh runs were unaffected,
   but anything that re-read a stored run (review and resume, policy preview, the API's invoice
   date) saw a broken value. Fixed with an explicit serializer and a type-restoring validator on
   the extraction model, with a regression test.
2. **Tax-inclusive invoice (S08) scored a false miss on "subtotal".** The invoice prints no
   subtotal, but the harness compared against the generator's computed taxable value. The truth
   for subtotal, buyer GSTIN and PO reference is now what is printed on the page.

## What changed for this run

- Default extraction model switched from `gemini-3.8-flash` to `gemini-3.5-flash-lite`: about 3 s
  per invoice instead of 15–20 s, with identical fields on the spot-checked S01, S04 and S05, and
  100% field accuracy across all 15 here.
- Cost is not estimated in this run (`LLM_PRICE_IN_PER_M` / `LLM_PRICE_OUT_PER_M` unset).

## Caveats

All invoices are synthetic, generated from one seeded world, and the two scanned ones are
simulated scans. Fifteen documents with one repeat is a small sample: it shows the pipeline and
policy behave as designed end to end, not a production accuracy rate. Raw reports
(`reports/eval_*.md`, `.json`) are regenerated on demand and kept out of git.
