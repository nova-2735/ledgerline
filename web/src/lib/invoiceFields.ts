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
  BANK_DETAILS_CHANGED: 'bank_account_number', FIELD_MISSING_INVOICE_NUMBER: 'invoice_number',
  FIELD_MISSING_INVOICE_DATE: 'invoice_date', FIELD_MISSING_TOTAL: 'total', FIELD_MISSING_SUPPLIER: 'supplier_name',
  VENDOR_GSTIN_MISMATCH: 'supplier_gstin', BUYER_GSTIN_MISMATCH: 'buyer_gstin', VENDOR_NOT_FOUND: 'supplier_name',
  DUPLICATE_SAME_INVOICE: 'invoice_number', MATH_TOTAL_MISMATCH: 'total', MATH_SUBTOTAL_MISMATCH: 'subtotal',
  DATE_IN_FUTURE: 'invoice_date', DATE_STALE: 'invoice_date', DATE_BEFORE_PO: 'invoice_date', PO_NOT_FOUND: 'po_reference',
}

export function checkField(check: Schemas['CheckResult']): FieldKey | null {
  const { field, fields, field_name } = check.evidence
  const names = [field, field_name, ...(Array.isArray(fields) ? fields : [])]
  for (const name of names) {
    if (typeof name === 'string' && Object.hasOwn(fieldLabels, name)) return name as FieldKey
  }
  return (check.code && linkedReasons[check.code]) ?? null
}
