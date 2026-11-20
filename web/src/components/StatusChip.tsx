import { Check, Circle, CircleAlert, Clock3, LoaderCircle } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { runStatuses } from '@/lib/labels'
import { cn } from '@/lib/utils'

const texts = { pass: 'Pass', warn: 'Warning', fail: 'Fail', skip: 'Skipped' }
const tones = { pass: 'bg-approve', warn: 'bg-hold', fail: 'bg-reject', skip: 'bg-faint' }

export function StatusChip({ status, severity, hint }: {
  status: Schemas['CheckStatus']; severity?: Schemas['Severity']; hint?: Schemas['Outcome'] | null
}) {
  const routineHold = hint === 'HOLD' && severity !== 'high' && severity !== 'critical'
  return <span className="status-chip text-muted-foreground">
    <span aria-hidden="true" className={cn('size-2 shrink-0', status === 'fail' && routineHold ? 'bg-hold' : tones[status])} />{texts[status]}
  </span>
}

const runStyles = {
  queued: [Circle, 'text-muted-foreground'], running: [LoaderCircle, 'text-primary'],
  awaiting_review: [Clock3, 'text-hold'], completed: [Check, 'text-muted-foreground'], failed: [CircleAlert, 'text-reject'],
} as const

export function RunStatusChip({ status }: { status: Schemas['RunStatus'] }) {
  const [Icon, color] = runStyles[status]
  return <span className={cn('status-chip', color)}>
    <Icon aria-hidden="true" className={status === 'running' ? 'motion-safe:animate-spin' : undefined} />{runStatuses[status]}
  </span>
}
