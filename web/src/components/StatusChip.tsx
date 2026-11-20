import { Check, Circle, CircleAlert, Clock3, LoaderCircle, Minus, X } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { runStatuses } from '@/lib/labels'
import { cn } from '@/lib/utils'

const icons = { pass: Check, warn: CircleAlert, fail: X, skip: Minus }
const texts = { pass: 'Pass', warn: 'Warning', fail: 'Fail', skip: 'Skipped' }
const tones = {
  pass: 'bg-emerald-50 text-emerald-800',
  warn: 'border border-amber-300 bg-white text-amber-800',
  fail: 'bg-rose-50 text-rose-800',
  skip: 'bg-slate-100 text-slate-600',
}

export function StatusChip({ status, severity, hint }: {
  status: Schemas['CheckStatus']
  severity?: Schemas['Severity']
  hint?: Schemas['Outcome'] | null
}) {
  const Icon = icons[status]
  const routineHold = hint === 'HOLD' && severity !== 'high' && severity !== 'critical'
  return (
    <span className={cn('status-chip', status === 'fail' && routineHold ? 'bg-amber-100 text-amber-900' : tones[status])}>
      <Icon aria-hidden="true" />{texts[status]}
    </span>
  )
}

const runStyles = {
  queued: [Circle, 'text-slate-600'],
  running: [LoaderCircle, 'text-indigo-700'],
  awaiting_review: [Clock3, 'text-amber-800'],
  completed: [Check, 'text-slate-700'],
  failed: [CircleAlert, 'text-rose-800'],
} as const

export function RunStatusChip({ status }: { status: Schemas['RunStatus'] }) {
  const [Icon, color] = runStyles[status]
  return <span className={cn('status-chip px-0', color)}>
    <Icon aria-hidden="true" className={status === 'running' ? 'motion-safe:animate-spin' : undefined} />
    {runStatuses[status]}
  </span>
}
