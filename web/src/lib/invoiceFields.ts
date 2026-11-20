import type { Schemas } from '@/api/client'

export const fieldGroups = {
  Invoice: { invoice_number: 'Invoice number', invoice_date: 'Invoice date', due_date: 'Due date', po_reference: 'Purchase order' },
  Supplier: { supplier_name: 'Supplier name', supplier_gstin: 'Supplier GSTIN', supplier_phone: 'Supplier phone' },
  Buyer: { buyer_name: 'Buyer name', buyer_gstin: 'Buyer GSTIN', place_of_supply: 'Place of supply' },
  Amounts: { subtotal: 'Subtotal', total: 'Invoice total', round_off: 'Round off', amount_in_words: 'Amount in words' },
  Bank: { bank_name: 'Bank name', bank_account_number: 'Account number', bank_ifsc: 'IFSC' },
} as const

type KeysOfUnion<T> = T extends T ? keyof T : never
export type FieldKey = KeysOfUnion<(typeof fieldGroups)[keyof typeof fieldGroups]>
export const fieldLabels = Object.assign({}, ...Object.values(fieldGroups)) as Record<FieldKey, string>
export const fieldKeys = Object.keys(fieldLabels) as FieldKey[]
export const criticalFields = ['invoice_number', 'invoice_date', 'supplier_gstin', 'total', 'bank_account_number'] as const

const linkedReasons: Partial<Record<Schemas['ReasonCode'], FieldKey>> = {
  VENDOR_BLOCKED: 'supplier_name', PO_VENDOR_MISMATCH: 'po_reference', PO_CLOSED: 'po_reference',
  DUPLICATE_SAME_FILE: 'invoice_number', TAX_TYPE_MISMATCH: 'place_of_supply', TAX_AMOUNT_MISMATCH: 'total',
  AMOUNT_VARIANCE_OVER_TOL: 'total', TOTAL_WORDS_MISMATCH: 'amount_in_words',
  BANK_DETAILS_CHANGED: 'bank_account_number', FIELD_MISSING_INVOICE_NUMBER: 'invoice_number',
  FIELD_MISSING_INVOICE_DATE: 'invoice_date', FIELD_MISSING_TOTAL: 'total', FIELD_MISSING_SUPPLIER: 'supplier_name',
  VENDOR_GSTIN_MISMATCH: 'supplier_gstin', BUYER_GSTIN_MISMATCH: 'buyer_gstin', VENDOR_NOT_FOUND: 'supplier_name',
  DUPLICATE_SAME_INVOICE: 'invoice_number', MATH_TOTAL_MISMATCH: 'total', MATH_SUBTOTAL_MISMATCH: 'subtotal',
  DATE_IN_FUTURE: 'invoice_date', DATE_STALE: 'invoice_date', DATE_BEFORE_PO: 'invoice_date', PO_NOT_FOUND: 'po_reference',
}

export function checkField(check: Schemas['CheckResult']): FieldKey | null {
  const { field, fields, field_name } = check.evidence
  const names = [field, field_name, ...(Array.isArray(fields) ? fields.map(item => item && typeof item === 'object' && 'field' in item ? item.field : item) : [])]
  for (const name of names) {
    if (typeof name === 'string' && Object.hasOwn(fieldLabels, name)) return name as FieldKey
  }
  return (check.code && linkedReasons[check.code]) ?? null
}

export interface InvoiceEvidence {
  id: string
  label: string
  bbox: Schemas['BBox'][]
  level: Schemas['ConfidenceLevel']
}

export function invoiceEvidence(check: Schemas['CheckResult'], extraction?: Schemas['RunDetail']['extraction']): InvoiceEvidence | null {
  if (!extraction) return null
  const lineNumber = check.evidence.invoice_line
  const line = typeof lineNumber === 'number' && extraction.line_items.find(item => item.index + 1 === lineNumber)
  if (line && line.bbox.length) {
    return { id: 'line-' + lineNumber, label: 'Invoice line ' + lineNumber, bbox: line.bbox, level: 'high' }
  }
  const field = checkField(check)
  if (!field || !extraction[field].bbox.length) return null
  return { id: field, label: fieldLabels[field], bbox: extraction[field].bbox, level: extraction[field].level }
}
