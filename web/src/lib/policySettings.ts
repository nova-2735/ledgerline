export const policyGroups = [
  { key: 'tolerances', label: 'Matching tolerances', description: 'How much invoice prices and totals can differ from the purchase order.' },
  { key: 'approval', label: 'Payment approval', description: 'When an invoice needs approval from the finance controller.' },
  { key: 'po_inference', label: 'Purchase order suggestions', description: 'How closely an invoice must match a purchase order for Ledgerline to suggest it.' },
  { key: 'duplicates', label: 'Duplicate invoices', description: 'How Ledgerline compares an invoice with earlier submissions.' },
  { key: 'extraction', label: 'Invoice reading', description: 'When a key value needs a human to check it.' },
  { key: 'dates', label: 'Invoice dates', description: 'How old an invoice can be and which date order Ledgerline reads first.' },
] as const

type SettingKind = 'money' | 'percent' | 'score' | 'days' | 'boolean' | 'text'

export const settingNames: Record<string, [label: string, kind: SettingKind]> = {
  unit_price_pct: ['Unit price tolerance (%)', 'percent'],
  header_pct: ['Allowed invoice total difference (%)', 'percent'],
  header_abs: ['Maximum invoice total difference (₹)', 'money'],
  rounding_abs: ['Rounding allowance (₹)', 'money'],
  misc_charge_abs: ['Allowance for small charges (₹)', 'money'],
  qty_pct: ['Quantity tolerance (%)', 'percent'],
  auto_approve_limit: ['Automatic approval limit (₹)', 'money'],
  auto_accept_inferred: ['Accept a clear PO match automatically', 'boolean'],
  min_score: ['Minimum match score (0–1)', 'score'],
  min_margin: ['Minimum lead over the next match (0–1)', 'score'],
  min_gap: ['Minimum lead over the next match (0–1)', 'score'],
  window_days: ['History checked for duplicates (days)', 'days'],
  lookback_days: ['History checked for duplicates (days)', 'days'],
  fuzzy_similarity: ['Minimum similarity for possible duplicates (0–1)', 'score'],
  fuzzy_amount_pct: ['Allowed amount difference (%)', 'percent'],
  fuzzy_date_window_days: ['Date difference for possible duplicates (days)', 'days'],
  min_confidence_critical: ['Minimum confidence for key fields (0–1)', 'score'],
  confidence_threshold: ['Minimum confidence for key fields (0–1)', 'score'],
  max_age_days: ['Maximum invoice age (days)', 'days'],
  stale_days: ['Maximum invoice age (days)', 'days'],
  future_days: ['Days allowed ahead of today', 'days'],
  order: ['Date order', 'text'],
}

export function policyGroup(policy: Record<string, unknown>, key: string): Record<string, unknown> {
  const group = policy[key]
  return typeof group === 'object' && group !== null && !Array.isArray(group) ? group as Record<string, unknown> : {}
}

export function validPolicyValue(kind: SettingKind, value: string) {
  if (kind === 'boolean') return value === 'true' || value === 'false'
  if (kind === 'score') return /^\d+(\.\d+)?$/.test(value) && Number(value) <= 1
  if (kind === 'days') return /^\d+$/.test(value) && Number.isSafeInteger(Number(value))
  if (kind === 'money' || kind === 'percent') return /^\d+(\.\d{1,2})?$/.test(value) && Number.isFinite(Number(value)) && (kind !== 'percent' || Number(value) <= 100)
  return true
}
