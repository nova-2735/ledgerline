import { CircleHelp } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { inr } from '@/lib/format'
import { actions, routes } from '@/lib/labels'

export function NextStepCard({ handoff, onAction, blockingApproval }: {
  handoff: Schemas['Handoff']; onAction: (action: Schemas['ActionType']) => void; blockingApproval?: string
}) {
  const offered = blockingApproval && !handoff.actions.includes('approve')
    ? [...handoff.actions, 'approve' as const] : handoff.actions
  return <section className="rounded-lg border border-indigo-200 bg-indigo-50/60 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold"><CircleHelp aria-hidden="true" className="size-4 text-indigo-700" />Next step</h3>
      <span className="status-chip bg-white text-indigo-900">{routes[handoff.owner]}</span>
    </div>
    <p className="mt-2 text-sm font-semibold">{handoff.question}</p>
    <p className="mt-1 text-sm text-slate-700">{handoff.suggested_action}</p>
    {handoff.amount_at_risk && <p className="mt-2 text-sm font-medium tabular-nums">{inr(handoff.amount_at_risk)} at risk</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      {offered.map((action, index) => action === 'approve' && blockingApproval ?
        <Tooltip key={action}><TooltipTrigger asChild>
          <span tabIndex={0} className="inline-flex rounded-md" aria-label={blockingApproval}><Button disabled size="sm">Approve</Button></span>
        </TooltipTrigger><TooltipContent>{blockingApproval}</TooltipContent></Tooltip>
        : <Button key={action} type="button" size="sm" variant={index === 0 ? 'default' : 'outline'} onClick={() => onAction(action)}>{actions[action]}</Button>)}
    </div>
  </section>
}
