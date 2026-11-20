import type { Schemas } from '@/api/client'

type Kpis = Schemas['StatsKpis']
type RunDetail = Schemas['RunDetail']
export type Metric = 'processed' | 'value_processed' | 'touchless_rate' | 'awaiting_review' | 'median_decision_ms' | 'exposure_stopped'
export const dayOutcomes = ['APPROVE', 'HOLD', 'RETURN', 'REJECT'] as const

export const outcomeLabels = { APPROVE: 'Approve', HOLD: 'Hold', RETURN: 'Return', REJECT: 'Reject' }

export function subtractPeriods(total: Kpis, recent: Kpis, metric: Metric) {
  if (metric === 'touchless_rate') {
    const previousCount = total.processed - recent.processed
    if (previousCount <= 0) return null
    const approvals = (s: Kpis) => Math.round(s.processed * s.touchless_rate)
    return (approvals(total) - approvals(recent)) / previousCount
  }
  if (metric === 'awaiting_review' || metric === 'median_decision_ms') return null
  return Number(total[metric]) - Number(recent[metric])
}

export const riskLabels = ['Duplicates', 'Bank change', 'Over-billing', 'Unknown vendor'] as const
type RiskType = typeof riskLabels[number]

function riskType(code?: string | null): RiskType | undefined {
  if (code?.startsWith('DUPLICATE_')) return 'Duplicates'
  if (code === 'BANK_DETAILS_CHANGED') return 'Bank change'
  if (code?.startsWith('QTY_EXCEEDS_') || code === 'PRICE_VARIANCE_OVER_TOL' || code === 'AMOUNT_VARIANCE_OVER_TOL') return 'Over-billing'
  if (code === 'VENDOR_NOT_FOUND' || code === 'VENDOR_BLOCKED') return 'Unknown vendor'
}

export function greatestRisk(run: RunDetail) {
  let amount = 0
  let type: RiskType | undefined
  for (const check of run.checks) {
    const group = riskType(check.code), value = Number(check.amount_at_risk)
    if (check.status === 'fail' && group && value > amount) { amount = value; type = group }
  }
  return { amount, type }
}

export function dayBefore(today: string, count: number) {
  const date = new Date(today + 'T00:00:00Z')
  date.setUTCDate(date.getUTCDate() - count)
  return date.toISOString().slice(0, 10)
}

export function age(hours: number) {
  if (hours < 1) return Math.max(1, Math.floor(hours * 60)) + ' min'
  return hours < 24 ? Math.floor(hours) + ' h' : Math.floor(hours / 24) + ' d'
}
