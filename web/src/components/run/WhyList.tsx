import { cn } from '@/lib/utils'
import type { Schemas } from '@/api/client'
import { StatusChip } from '@/components/StatusChip'
import { inr } from '@/lib/format'
import { checkField, invoiceEvidence, type InvoiceEvidence, type FieldKey } from '@/lib/invoiceFields'

export function WhyList({ checks, onHighlight, onEvidence, extraction }: {
  extraction?: Schemas['RunDetail']['extraction']; onEvidence?: (target: InvoiceEvidence) => void; checks: Schemas['CheckResult'][]; onHighlight: (field: FieldKey | null) => void
}) {
  const why = [...checks.filter(check => check.status === 'fail'), ...checks.filter(check => check.status === 'warn')]
  const notes = why.filter(check => check.status === 'warn').length
  const issues = why.length - notes
  const passed = checks.filter(check => check.status === 'pass')
  const list = (rows: Schemas['CheckResult'][]) => <ul className="divide-y">
    {rows.map((check, index) => {
      const field = checkField(check)
      const target = invoiceEvidence(check, extraction)
      return <li key={check.rule_id + '-' + index}
        className={cn('space-y-1 p-2.5 hover:bg-muted', check.severity === 'critical' && 'border-l-2 border-l-reject')}
        tabIndex={field ? 0 : undefined}
        onMouseEnter={() => onHighlight(field)} onMouseLeave={() => onHighlight(null)}
        onFocus={() => onHighlight(field)} onBlur={() => onHighlight(null)}>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusChip status={check.status} severity={check.severity} hint={check.outcome_hint} />
          <strong className="text-sm">{check.title}</strong>
          {check.resolved_by_review && <span className="text-meta font-medium text-approve">Resolved in review</span>}
        </div>
        <p className="text-sm text-muted-foreground">{check.message}</p>
        {target && onEvidence ? <button type="button" className="text-link text-meta" onClick={() => onEvidence(target)}>Show {target.label.toLowerCase()} on invoice</button> :
          check.status === 'fail' && <p className="text-meta text-muted-foreground">No printed location for this check.</p>}
        {check.amount_at_risk && <p className="text-xs font-medium tabular-nums">{inr(check.amount_at_risk)} at risk</p>}
        {Object.keys(check.evidence).length > 0 && <details className="text-xs">
          <summary className="cursor-pointer font-medium text-primary">Details</summary>
          <pre className="mt-1 max-h-32 overflow-auto rounded-sm bg-muted p-2 font-sans whitespace-pre-wrap wrap-anywhere">{JSON.stringify(check.evidence, null, 2)}</pre>
        </details>}
      </li>
    })}
  </ul>
  return <details className="panel p-2.5"><summary className="cursor-pointer text-section">What we checked <span className="ml-1 text-meta font-normal text-muted-foreground">{passed.length} passed · {notes} {notes === 1 ? 'note' : 'notes'} · {issues} {issues === 1 ? 'issue' : 'issues'}</span></summary><div className="mt-2 space-y-3">
    {!!why.length && <section><h3 className="section-title mb-2">Why</h3><div className="overflow-hidden rounded-sm border">{list(why)}</div></section>}
    {!!passed.length && <details className="rounded-sm border">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{passed.length} {passed.length === 1 ? 'check' : 'checks'} passed</summary>
      {list(passed)}
    </details>}
  </div></details>
}
