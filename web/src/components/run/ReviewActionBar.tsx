import type { Schemas } from '@/api/client'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { actions } from '@/lib/labels'
import { actionShortcut } from './reviewActions'

const barLabels: Partial<Record<Schemas['ActionType'], string>> = {
  verify_bank: 'Verify bank', correct_fields: 'Correct fields', send_to_vendor: 'Send to vendor',
}

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
  return <div className="flex flex-wrap items-center gap-1.5 border-t p-2.5" aria-label="Review actions">
    {offered.map((action, i) => {
      const key = actionShortcut(action)
      return action === 'approve' && blockingApproval ? <BlockedApproval key={action} reason={blockingApproval} /> :
        <Button key={action} type="button" size="sm" variant={i === 0 ? 'default' : 'outline'} onClick={() => onAction(action)}>
          {barLabels[action] ?? actions[action]}{key && <ShortcutHint id={key} />}
        </Button>
    })}
  </div>
}
