import { Info } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { actionLabel, actionShortcut } from './reviewActions'

export function BlockedApproval({ reason }: { reason: string }) {
  return <Tooltip>
    <TooltipTrigger asChild><span className="inline-flex" tabIndex={0} title={reason}>
      <Button variant="outline" disabled size="sm">Approve<ShortcutHint id="approve" /></Button>
    </span></TooltipTrigger>
    <TooltipContent>{reason}</TooltipContent>
  </Tooltip>
}

export function ReviewActionBar({ offered, blockingApproval, onAction }: {
  offered: Schemas['ActionType'][]; blockingApproval?: string; onAction: (action: Schemas['ActionType']) => void
}) {
  if (!offered.length) return null
  const approvalBlocked = Boolean(blockingApproval && offered.includes('approve'))
  return <div className="border-t p-2.5" aria-label="Review actions">
    <div className="flex flex-wrap items-center gap-1.5">
      {offered.map((action, i) => {
        const key = actionShortcut(action)
        return action === 'approve' && blockingApproval ? <BlockedApproval key={action} reason={blockingApproval} /> :
          <Button key={action} type="button" size="sm" variant={i === 0 ? 'default' : 'outline'} onClick={() => onAction(action)}>
            {actionLabel(action)}{key && <ShortcutHint id={key} />}
          </Button>
      })}
    </div>
    {approvalBlocked && <p role="note" className="mt-2 flex gap-1.5 text-body text-muted-foreground">
      <Info aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" /><span><span className="font-medium text-foreground">Approve is unavailable.</span> {blockingApproval}</span>
    </p>}
  </div>
}
