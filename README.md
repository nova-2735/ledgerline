# Ledgerline

Ledgerline turns a PDF invoice into a reasoned accounts-payable decision. It reads the document
(Gemini transcribes it, deterministic code parses it), checks it against the vendor master,
purchase orders, goods receipts and earlier invoices, and returns approve, hold, return or reject
with the reasons behind it. Every step is visible in a live run view and a dashboard. Setup:
`make setup`, then `make dev` (API on :8000, web on :5173).
