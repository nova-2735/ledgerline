import type { Schemas } from '@/api/client'

export const stages = {
  intake: 'Receive invoice', read_document: 'Read PDF', extract_fields: 'Extract invoice fields',
  validate_document: 'Validate invoice', identify_vendor: 'Identify vendor', check_tax: 'Check GST',
  resolve_po: 'Find purchase order', match_lines: 'Match line items', check_duplicates: 'Check duplicates',
  decide: 'Make decision', explain_route: 'Explain and route',
} satisfies Record<Schemas['StageName'], string>

export const routes = {
  none: 'No review needed', ap_clerk: 'AP team', buyer: 'Buyer', receiving: 'Receiving',
  treasury: 'Treasury', procurement: 'Procurement', controller: 'Finance controller', vendor: 'Vendor',
} satisfies Record<Schemas['Route'], string>

export const outcomes = {
  APPROVE: 'Approve for payment', HOLD: 'Hold for review', RETURN: 'Return to vendor', REJECT: 'Reject',
} satisfies Record<Schemas['Outcome'], string>

export const runStatuses = {
  queued: 'Queued', running: 'Running…', awaiting_review: 'Awaiting review', completed: 'Completed', failed: 'Failed',
} satisfies Record<Schemas['RunStatus'], string>

export const sources = {
  demo: 'Demo', upload: 'Upload', email: 'Email', seed: 'Seeded',
} satisfies Record<Schemas['RunSource'], string>

export const reasons = {
  DOC_NOT_INVOICE: 'Document is not an invoice', DOC_PROFORMA: 'Proforma invoice', DOC_CREDIT_NOTE: 'Credit note',
  DOC_UNREADABLE: 'Unreadable document', FIELD_MISSING_INVOICE_NUMBER: 'Missing invoice number',
  FIELD_MISSING_INVOICE_DATE: 'Missing invoice date', FIELD_MISSING_TOTAL: 'Missing invoice total',
  FIELD_MISSING_SUPPLIER: 'Missing supplier name', FIELD_LOW_CONFIDENCE: 'Invoice fields need verification',
  MATH_LINE_MISMATCH: 'Line amount does not add up', MATH_SUBTOTAL_MISMATCH: 'Subtotal does not add up',
  MATH_TOTAL_MISMATCH: 'Total does not add up', ROUND_OFF_APPLIED: 'Rounding applied',
  TAX_INCLUSIVE_NORMALIZED: 'Tax included in price', TOTAL_WORDS_MISMATCH: 'Written total differs',
  DATE_IN_FUTURE: 'Invoice dated in the future', DATE_STALE: 'Invoice is overdue for submission',
  VENDOR_NOT_FOUND: 'Unknown vendor', VENDOR_BLOCKED: 'Vendor blocked', VENDOR_GSTIN_MISMATCH: 'Vendor GSTIN differs',
  VENDOR_MATCHED_BY_NAME: 'Vendor matched by name', BANK_DETAILS_CHANGED: 'Bank details changed',
  SENDER_DOMAIN_MISMATCH: 'Sender email domain differs', GSTIN_INVALID: 'Invalid GSTIN',
  BUYER_GSTIN_MISMATCH: 'Buyer GSTIN differs', TAX_TYPE_MISMATCH: 'Incorrect GST type',
  TAX_AMOUNT_MISMATCH: 'Incorrect GST amount', TAX_RATE_MISMATCH: 'Incorrect GST rate',
  PO_NOT_FOUND: 'Purchase order not found', PO_INFERRED: 'Purchase order needs confirmation',
  PO_AMBIGUOUS: 'Multiple possible purchase orders', PO_MISSING: 'Missing purchase order',
  PO_VENDOR_MISMATCH: 'Purchase order belongs to another vendor', PO_CLOSED: 'Purchase order closed',
  CURRENCY_MISMATCH: 'Invoice currency differs', DATE_BEFORE_PO: 'Invoice predates purchase order',
  LINE_NOT_ON_PO: 'Item missing from purchase order', MISC_CHARGE_ALLOWED: 'Additional charge allowed',
  LINES_BUNDLED: 'Items billed together', PRICE_VARIANCE_WITHIN_TOL: 'Price within tolerance',
  PRICE_VARIANCE_OVER_TOL: 'Unit price exceeds tolerance', PRICE_BELOW_PO: 'Price below order price',
  AMOUNT_VARIANCE_OVER_TOL: 'Invoice amount exceeds tolerance', QTY_EXCEEDS_PO_REMAINING: 'Billed above remaining order',
  QTY_EXCEEDS_RECEIVED: 'Billed more than received', GOODS_NOT_RECEIVED: 'Goods not received',
  DUPLICATE_SAME_FILE: 'Duplicate file', DUPLICATE_SAME_INVOICE: 'Duplicate invoice',
  DUPLICATE_SUSPECTED: 'Possible duplicate', APPROVAL_LIMIT_EXCEEDED: 'Above approval limit',
  POSTING_INCOMPLETE: 'Posting incomplete',
} satisfies Record<Schemas['ReasonCode'], string>

export const actions = {
  approve: 'Approve', reject: 'Reject', send_to_vendor: 'Return to vendor', confirm_po: 'Confirm PO',
  verify_bank: 'Verify bank details', correct_fields: 'Verify invoice fields', not_duplicate: 'Mark as distinct',
  reopen: 'Reopen',
} satisfies Record<Schemas['ActionType'], string>
