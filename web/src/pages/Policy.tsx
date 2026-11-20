import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CalendarDays, CircleCheck, CopyCheck, FileSearch, ScanText, SlidersHorizontal } from 'lucide-react'
import { api } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { PolicyPreview, policyGroup } from '@/components/PolicyPreview'
import { Button } from '@/components/ui/button'
import { inr, pct } from '@/lib/format'

const groups = [
  { key: 'tolerances', label: 'Matching tolerances', icon: SlidersHorizontal, description: 'How much invoice prices and totals can differ from the purchase order.' },
  { key: 'approval', label: 'Payment approval', icon: CircleCheck, description: 'When an invoice needs approval from the finance controller.' },
  { key: 'po_inference', label: 'Purchase order suggestions', icon: FileSearch, description: 'How closely an invoice must match a purchase order for Ledgerline to suggest it.' },
  { key: 'duplicates', label: 'Duplicate invoices', icon: CopyCheck, description: 'How Ledgerline compares invoices with earlier submissions.' },
  { key: 'extraction', label: 'Invoice reading', icon: ScanText, description: 'When an extracted value needs a human to check it.' },
  { key: 'dates', label: 'Invoice dates', icon: CalendarDays, description: 'How old an invoice can be and how far ahead it can be dated.' },
] as const

const settingLabels: Record<string, string> = {
  unit_price_pct: 'Allowed increase above the PO unit price',
  header_pct: 'Allowed invoice total difference',
  header_abs: 'Maximum invoice total difference',
  auto_approve_limit: 'Automatic approval limit',
  min_score: 'Minimum match score',
  min_gap: 'Minimum lead over the next match',
  lookback_days: 'History checked for duplicates',
  confidence_threshold: 'Minimum confidence for key fields',
  stale_days: 'Maximum invoice age',
  future_days: 'Days allowed ahead of today',
}
const currencySettings = new Set(['header_abs', 'auto_approve_limit'])
const scoreSettings = new Set(['min_score', 'min_gap', 'confidence_threshold'])

function formatSetting(key: string, value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'boolean') return value ? 'On' : 'Off'
  if (Array.isArray(value)) return value.map(item => String(item)).join(', ')
  if (typeof value === 'object') return Object.entries(value).map(([name, item]) => `${name.replaceAll('_', ' ')} ${formatSetting(name, item)}`).join(' · ')
  if (currencySettings.has(key)) return inr(String(value))
  if (key.endsWith('_pct')) return pct(Number(value) / 100)
  if (scoreSettings.has(key)) return pct(Number(value))
  if (key.endsWith('_days')) return `${value} ${Number(value) === 1 ? 'day' : 'days'}`
  return String(value)
}

export function Policy() {
  const [editing, setEditing] = useState(false)
  const policy = useQuery({
    queryKey: queryKeys.policy,
    queryFn: ({ signal }) => api.policy(signal),
  })
  return <div className="space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h1 className="page-title">Policy</h1>
        <p className="mt-1 text-sm text-muted-foreground">Review the rules Ledgerline uses to decide what happens to each invoice.</p>
      </div>
      {policy.data && <div className="flex flex-wrap items-center gap-2">
        <p className="status-chip border bg-white text-slate-700">Version {policy.data.version}</p>
        {!editing && <Button type="button" size="sm" onClick={() => setEditing(true)}>Try policy changes</Button>}
      </div>}
    </header>
    {policy.isPending && <div className="panel"><LoadingState label="Loading invoice policy" /></div>}
    {policy.isError && <ErrorState title="Could not load the policy" error={policy.error} retry={() => void policy.refetch()} />}
    {policy.data && !Object.keys(policy.data.policy).length && <div className="panel"><EmptyState title="No policy settings are available" /></div>}
    {policy.data && editing && <PolicyPreview key={policy.data.version} policy={policy.data} onClose={() => setEditing(false)} />}
    {policy.data && Object.keys(policy.data.policy).length > 0 && <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {groups.map(({ key, label, description, icon: Icon }) => {
        const settings = Object.entries(policyGroup(policy.data!.policy, key))
        return <article key={key} className="panel min-w-0 p-4">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 shrink-0 place-items-center rounded-md bg-indigo-50 text-indigo-700"><Icon className="size-4" aria-hidden="true" /></span>
            <h2 className="section-title">{label}</h2>
          </div>
          <p className="mt-2 min-h-10 text-sm text-muted-foreground">{description}</p>
          {settings.length ? <dl className="mt-2 divide-y border-t">
            {settings.map(([name, value]) => <div key={name} className="flex items-baseline justify-between gap-4 py-2 text-sm">
              <dt className="first-letter:uppercase">{settingLabels[name] ?? name.replaceAll('_', ' ')}</dt>
              <dd className="text-right font-medium wrap-anywhere tabular-nums">{formatSetting(name, value)}</dd>
            </div>)}
          </dl> : <p className="mt-3 border-t pt-2 text-sm text-muted-foreground">No settings available.</p>}
        </article>
      })}
    </div>}
  </div>
}
