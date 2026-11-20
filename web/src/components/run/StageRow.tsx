import { Check, ChevronRight, Circle, CircleAlert, LoaderCircle, Minus, TriangleAlert, X } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { StatusChip } from '@/components/StatusChip'
import { duration } from '@/lib/format'
import { checkField, type FieldKey } from '@/lib/invoiceFields'
import { stages } from '@/lib/labels'
import { cn } from '@/lib/utils'

const signals = {
  pending: [Circle, 'Pending', 'text-faint'],
  running: [LoaderCircle, 'Running', 'text-primary'],
  passed: [Check, 'Passed', 'text-approve'],
  warned: [CircleAlert, 'Warning', 'text-hold'],
  failed: [X, 'Failed', 'text-reject'],
  skipped: [Minus, 'Skipped', 'text-muted-foreground'],
  error: [TriangleAlert, 'Error', 'text-reject'],
} as const

export function StageRow({ stage, index, expanded, toggle, checks, log, onHighlight }: {
  stage: Schemas['StageState']; index: number; expanded: boolean; toggle: () => void
  checks: Schemas['CheckResult'][]; log?: string | null
  onHighlight: (field: FieldKey | null) => void
}) {
  const [Icon, status, tone] = signals[stage.status]
  const running = stage.status === 'running'
  const message = running ? log ?? 'Working…' : stage.summary
  return <div className="border-b" data-stage={stage.name} data-status={stage.status}>
    <button type="button" id={'stage-toggle-' + stage.name} aria-expanded={expanded} aria-controls={'stage-detail-' + stage.name} onClick={toggle}
      className={cn('flex min-h-9 w-full items-center gap-2 border-l-2 border-l-transparent px-2 text-left hover:bg-muted', running && 'border-l-primary bg-accent hover:bg-accent', expanded && !running && 'bg-muted')}>
      <span className="identifier shrink-0 text-muted-foreground">{String(index + 1).padStart(2, '0')}</span>
      <Icon aria-hidden="true" className={cn('size-3.5 shrink-0', tone, running && 'motion-safe:animate-spin')} />
      <span className="min-w-0 flex-1 py-1">
        <span className="block truncate text-body font-medium" title={stages[stage.name]}>{stages[stage.name]}<span className="sr-only"> · {status}</span></span>
        {running && <span className="block truncate text-meta text-muted-foreground" title={message ?? undefined}>{message}</span>}
      </span>
      {stage.duration_ms != null && <span className="shrink-0 text-right text-meta text-muted-foreground">{duration(stage.duration_ms)}</span>}
      <ChevronRight aria-hidden="true" className={cn('size-3.5 shrink-0 text-faint duration-150', expanded && 'rotate-90')} />
    </button>
    {expanded && <div id={'stage-detail-' + stage.name} className="space-y-2 border-t bg-muted p-2.5 text-meta">
      {message && <p className="text-muted-foreground">{message}</p>}
      {checks.map((check, i) => {
        const field = checkField(check)
        return <div key={check.rule_id + '-' + i} tabIndex={field ? 0 : undefined}
          className={cn('space-y-1 border bg-card p-2', check.severity === 'critical' && 'border-l-2 border-l-reject')}
          onMouseEnter={() => onHighlight(field)} onMouseLeave={() => onHighlight(null)} onFocus={() => onHighlight(field)} onBlur={() => onHighlight(null)}>
          <div className="flex flex-wrap items-center gap-1.5"><StatusChip status={check.status} severity={check.severity} hint={check.outcome_hint} /><strong>{check.title}</strong></div>
          <p className="text-muted-foreground">{check.message}</p>
        </div>
      })}
      {Object.keys(stage.detail).length > 0 && <details className="border bg-card p-2">
        <summary className="cursor-pointer font-medium">Details</summary>
        <pre className="mt-2 max-h-44 overflow-auto font-sans whitespace-pre-wrap wrap-anywhere text-muted-foreground">{JSON.stringify(stage.detail, null, 2)}</pre>
      </details>}
      {!message && !checks.length && <p className="text-muted-foreground">Details appear as this step runs.</p>}
    </div>}
  </div>
}
