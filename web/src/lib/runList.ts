import type { Schemas } from '@/api/client'

export type Run = Schemas['RunSummary']

export const runViews = [
  ['all', 'All'],
  ['review', 'Needs review'],
  ['exceptions', 'Exceptions'],
  ['approved', 'Approved'],
  ['closed', 'Returned/Rejected'],
] as const

export type RunView = typeof runViews[number][0]
export const effectiveOutcome = (run: Run) => run.final_outcome ?? run.outcome

export function inView(run: Run, view: RunView) {
  const outcome = effectiveOutcome(run)
  switch (view) {
    case 'review': return run.status === 'awaiting_review'
    case 'exceptions': return run.status === 'failed' || (outcome != null && outcome !== 'APPROVE')
    case 'approved': return outcome === 'APPROVE'
    case 'closed': return outcome === 'RETURN' || outcome === 'REJECT'
    default: return true
  }
}

const dayFormat = new Intl.DateTimeFormat('sv-SE', { dateStyle: 'short', timeZone: 'Asia/Kolkata' })
export const dayOf = (date: string) => dayFormat.format(new Date(date))

const csvCell = (value: string | number | null | undefined) => {
  const text = value == null ? '' : String(value)
  const safe = typeof value === 'string' && /^\s*[=+@-]/.test(text) ? "'" + text : text
  return '"' + safe.replaceAll('"', '""') + '"'
}

export function downloadRuns(runs: Run[]) {
  const header = ['Outcome', 'Run', 'Received (UTC)', 'Vendor', 'Invoice #', 'PO', 'Amount (INR)', 'Reason', 'Owner', 'Time (ms)', 'Source']
  const rows = runs.map(r => [effectiveOutcome(r), r.display_id, r.created_at, r.vendor_name, r.invoice_number, r.po_number,
    r.total == null ? null : Number(r.total), r.primary_reason, r.route, r.duration_ms, r.source])
  const csv = [header, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'ledgerline-runs.csv'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
