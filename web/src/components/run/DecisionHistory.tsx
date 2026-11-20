import type { Schemas } from '@/api/client'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { istDate, istTime } from '@/lib/format'

export function DecisionHistory({ decisions, reviews }: { decisions: Schemas['Decision'][]; reviews: Schemas['ReviewAction'][] }) {
  if (!decisions.length) return null
  return <section className="space-y-2">
    <h3 className="section-title">Decision history</h3>
    <ol className="divide-y rounded-lg border">
      {decisions.map(decision => {
        const review = reviews.find(action => action.resulting_decision_version === decision.version)
        return <li key={decision.version} className="space-y-1 p-2.5">
          <div className="flex flex-wrap items-center gap-2 text-xs tabular-nums">
            <span className="font-semibold">v{decision.version}</span><OutcomeBadge outcome={decision.outcome} />
            <time dateTime={decision.decided_at} className="text-muted-foreground">{istDate(decision.decided_at)} · {istTime(decision.decided_at)}</time>
          </div>
          {review && <p className="text-sm"><strong>{review.reviewer}</strong> · {review.note}</p>}
        </li>
      })}
    </ol>
  </section>
}
