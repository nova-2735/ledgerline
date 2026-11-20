import { Check, ChevronDown, Circle, CircleAlert, LoaderCircle, Minus, TriangleAlert, X } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { StatusChip } from '@/components/StatusChip'
import { duration } from '@/lib/format'
import { checkField, type FieldKey } from '@/lib/invoiceFields'

const signals = {
  pending: [Circle, 'Pending', 'bg-slate-50 text-slate-400'],
  running: [LoaderCircle, 'Running', 'bg-indigo-100 text-indigo-700'],
  passed: [Check, 'Passed', 'bg-emerald-50 text-emerald-700'],
  warned: [CircleAlert, 'Warning', 'bg-amber-50 text-amber-700'],
  failed: [X, 'Failed', 'bg-rose-50 text-rose-700'],
  skipped: [Minus, 'Skipped', 'bg-slate-100 text-slate-600'],
  error: [TriangleAlert, 'Error', 'bg-rose-100 text-rose-800'],
} as const

const labels = {
  intake: 'Received the invoice', read_document: 'Read the document', extract_fields: 'Pulled out the details',
  validate_document: 'Checked the document', identify_vendor: 'Identified the vendor', check_tax: 'Checked GST',
  resolve_po: 'Found the purchase order', match_lines: 'Matched the lines', check_duplicates: 'Looked for duplicates',
  decide: 'Made a decision', explain_route: 'Explained and routed it',
} satisfies Record<Schemas['StageName'], string>

export function StageRow({ stage, checks, log, onHighlight }: {
  stage: Schemas['StageState']; checks: Schemas['CheckResult'][]; log?: string | null
  onHighlight: (field: FieldKey | null) => void
}) {
  const [Icon, status, tone] = signals[stage.status]
  const running = stage.status === 'running'
  const message = running ? log ?? 'Working…' : stage.summary
  return <details className="group border-b last:border-b-0" data-stage={stage.name} data-status={stage.status}>
    <summary className="flex min-h-[57px] cursor-pointer list-none items-center gap-2.5 px-3 py-2 hover:bg-slate-50 [&::-webkit-details-marker]:hidden">
      <span key={stage.status} className={`grid size-7 shrink-0 place-items-center rounded-full transition-colors duration-200 ${tone}`} title={status}>
        <Icon aria-hidden="true" className={`size-4 ${running ? 'motion-safe:animate-spin' : ''}`} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[0.82rem] leading-5 font-medium text-slate-900">{labels[stage.name]}<span className="sr-only"> · {status}</span></div>
        <div className="min-h-4 truncate text-xs text-muted-foreground" title={message ?? undefined}>{message ?? ' '}</div>
      </div>
      {stage.duration_ms != null && <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{duration(stage.duration_ms)}</span>}
      <ChevronDown aria-hidden="true" className="size-3.5 shrink-0 text-slate-500 group-open:rotate-180" />
    </summary>
    <div className="space-y-2 bg-slate-50 px-3 pb-3 text-xs">
      {message && <p className="pt-1 text-slate-700">{message}</p>}
      {checks.map(check => {
        const field = checkField(check)
        return <div key={check.rule_id} tabIndex={field ? 0 : undefined} className="space-y-1 rounded-md border bg-white p-2"
          onMouseEnter={() => onHighlight(field)} onMouseLeave={() => onHighlight(null)}
          onFocus={() => onHighlight(field)} onBlur={() => onHighlight(null)}>
          <div className="flex flex-wrap items-center gap-1"><StatusChip status={check.status} severity={check.severity} hint={check.outcome_hint} /><strong>{check.title}</strong></div>
          <div className="text-slate-700">{check.message}</div>
        </div>
      })}
      {Object.keys(stage.detail).length > 0 && <details className="rounded border bg-white p-2">
        <summary className="cursor-pointer font-medium">Details</summary>
        <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap wrap-anywhere text-slate-700">{JSON.stringify(stage.detail, null, 2)}</pre>
      </details>}
      {!message && !checks.length && <p className="pt-1 text-muted-foreground">Details appear as this step runs.</p>}
    </div>
  </details>
}
