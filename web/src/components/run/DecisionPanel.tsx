import { ShieldAlert } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { EmptyState } from '@/components/EmptyState'
import { OutcomeBadge, outcomeColors } from '@/components/OutcomeBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import type { FieldKey } from '@/lib/invoiceFields'
import { DecisionHistory } from './DecisionHistory'
import { DraftCard } from './DraftCard'
import { NextStepCard } from './NextStepCard'
import { PostingTable } from './PostingTable'
import { WhyList } from './WhyList'
import { BlockedApproval } from './ReviewActionBar'
import { approvalBlock } from './reviewActions'

export function DecisionPanel({ run, onAction, onHighlight }: {
  run: Schemas['RunDetail']; onAction: (action: Schemas['ActionType']) => void; onHighlight: (field: FieldKey | null) => void
}) {
  const decision = run.decision
  if (!decision) return <EmptyState title={run.status === 'failed' ? 'This run ended without a decision' : 'Decision pending'}>
    {run.status === 'failed' ? 'See the stage timeline for the step that failed.' : 'The outcome appears here when the invoice checks are complete.'}
  </EmptyState>
  const blocker = approvalBlock(run)
  const critical = run.checks.find(check => check.severity === 'critical' && !check.resolved_by_review && (check.status === 'fail' || check.status === 'warn'))
  const draft = decision.explanation.vendor_message
  return <div className="space-y-3">
    <section className="border border-l-[3px] bg-card px-3 py-2.5" style={{ borderLeftColor: outcomeColors[decision.outcome] }}>
      <OutcomeBadge outcome={decision.outcome} />
      <h3 className="mt-1 text-title">{decision.headline}</h3>
    </section>
    {critical && <Alert variant="destructive" className="rounded-none border-l-2 border-l-reject bg-card text-reject">
      <ShieldAlert aria-hidden="true" /><AlertTitle>{critical.code === 'BANK_DETAILS_CHANGED' ? 'Possible payment-redirection attempt' : 'Critical check needs attention'}</AlertTitle>
      <AlertDescription className="flex flex-wrap items-center gap-2 text-body text-muted-foreground!">{blocker ?? critical.title}
        {blocker && !decision.handoff?.actions.includes('approve') && <BlockedApproval reason={blocker} />}</AlertDescription>
    </Alert>}
    {decision.handoff && <NextStepCard handoff={decision.handoff} onAction={onAction} blockingApproval={blocker} />}
    <details className="panel px-2.5 py-2">
      <summary className="cursor-pointer text-section">Decision explanation</summary>
      <p className="mt-1.5 text-body text-muted-foreground">{decision.explanation.summary}</p>
      {!!decision.notes.length && <ul className="mt-2 list-disc space-y-1 pl-4 text-body text-muted-foreground">
        {decision.notes.map(note => <li key={note}>{note}</li>)}
      </ul>}
    </details>
    <WhyList checks={run.checks} onHighlight={onHighlight} />
    {draft && <DraftCard draft={draft} markAsSent={decision.handoff?.actions.includes('send_to_vendor') ? () => onAction('send_to_vendor') : undefined} />}
    {decision.explanation.internal_note && <DraftCard draft={decision.explanation.internal_note} />}
    {decision.outcome === 'APPROVE' && decision.posting && <PostingTable posting={decision.posting} />}
    <DecisionHistory decisions={run.decision_history.filter(item => item.version <= decision.version)} reviews={run.review_actions} />
    <p className="border-t pt-2 text-xs text-muted-foreground">Decided by policy {decision.policy_version} · Explanation written by {decision.explanation.generated_by === 'llm' ? 'the model' : 'template'}</p>
  </div>
}
