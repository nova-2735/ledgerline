# Assumptions

- "Today" is the Asia/Kolkata business date; with `APP_TODAY` set, `clock.now()` keeps the real time of day but pins the date to `APP_TODAY` (IST), returned in UTC.
- Reader output shapes (`Word`, `PageRead`, `DocumentRead`) live in `backend/app/models/extraction.py`; `ingest/reader.py` produces them.
- Money fields (amounts, unit prices, totals, tax) are 2 dp `Money`; quantities, rates and percentages are exact decimals; both travel as JSON strings and floats are rejected.
- Money is stored in the database as integer paise so SQLite sums stay exact.
- Audit export shape is `{run: RunDetail, events: RunEvent[], raw_model_output}`.
