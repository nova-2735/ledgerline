# Assumptions

- "Today" is the Asia/Kolkata business date; with `APP_TODAY` set, `clock.now()` keeps the real time of day but pins the date to `APP_TODAY` (IST), returned in UTC.
- Reader output shapes (`Word`, `PageRead`, `DocumentRead`) live in `backend/app/models/extraction.py`; `ingest/reader.py` produces them.
- Money fields (amounts, unit prices, totals, tax) are 2 dp `Money`; quantities, rates and percentages are exact decimals; both travel as JSON strings and floats are rejected.
- Money is stored in the database as integer paise so SQLite sums stay exact.
- Audit export shape is `{run: RunDetail, events: RunEvent[], raw_model_output}`.
- Demo world: street addresses for all vendors and Om Sai Traders (plus Om Sai's phone and bank) are invented; SCENARIOS gives only city and state.
- Demo world: routine-PO details SCENARIOS leaves open are assumed — SW-NIM-SUP / SW-NIM-ANL use SAC 997331, hair nets HSN 6505, FM-DC-01 SAC 998533 with unit "Job".
- Print style: only V004 and Om Sai print totals with "/-"; V009 prints "Rs. 47,250.00" (per-vendor table in SCENARIOS §3 wins over the template note).
- Print style: line GST rates are printed only by the `modern` template, item codes only by `classic_gst` and `modern`; no template prints a due date, so these are null in truth.
- Ground truth: `raw.total` includes the currency mark as printed (e.g. "Rs. 1,16,348.00", "INR 472,000.00"); `raw.po_reference` is the value after the label; printed notes and notices are listed in `annotations` with stamps and handwriting; `legibility` is "clear" for every document.
- Ground truth: H19 is a byte copy of H14, so `truth/index.json` maps their shared sha256 to H14.
- With no font carrying ₹ (INVOICE_FONT_PATH unset and no DejaVuSans), every "₹" vendor prints "Rs."; generator output is byte-identical across runs on the same machine and font set.
- Scan rotation follows PIL: positive degrees rotate counter-clockwise.
