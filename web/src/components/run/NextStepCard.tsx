import type { Schemas } from '@/api/client'
import { inr } from '@/lib/format'
import { routes } from '@/lib/labels'
import { ReviewActionBar } from './ReviewActionBar'

export function NextStepCard({ handoff, onAction, blockingApproval }: {
  handoff: Schemas['Handoff']; onAction: (action: Schemas['ActionType']) => void; blockingApproval?: string
}) {
  return <section className="panel">
    <div className="flex min-h-8 items-center justify-between gap-2 border-b bg-muted px-2.5 py-1">
      <h3 className="text-section">Next step</h3>
      <span className="rounded-sm border bg-card px-1.5 py-0.5 text-meta text-muted-foreground">{routes[handoff.owner]}</span>
    </div>
    <div className="space-y-1.5 p-2.5">
      {handoff.question && <p className="font-medium">{handoff.question}</p>}
      <p className="text-body text-muted-foreground">{handoff.suggested_action}</p>
      {handoff.amount_at_risk && <p className="text-meta font-medium">{inr(handoff.amount_at_risk)} at risk</p>}
    </div>
    <ReviewActionBar offered={handoff.actions} blockingApproval={blockingApproval} onAction={onAction} />
  </section>
}
