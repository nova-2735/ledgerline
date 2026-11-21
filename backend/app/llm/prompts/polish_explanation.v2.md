---
id: polish_explanation
version: v2
model_hint: LLM_MODEL_LIGHT
output_schema: text
---
Rewrite the summary below for a non-technical accounts-payable manager.

Rules:
- Start with the outcome word (Approve, Hold, Return or Reject) in normal sentence case, never
  in capitals, and keep its meaning.
- Keep every number, amount, date, invoice number, PO number and masked account number (such as
  ****8901) exactly as written.
- Say who has to act when the summary names them (an AP clerk, the buyer, treasury,
  procurement, the receiving team, the finance controller).
- Do not add facts, reasons or advice that are not in the summary or the facts list.
- Plain, calm, specific English. At most 80 words. No headings, no bullet points.

Return only the rewritten summary text.
