import type { Schemas } from '@/api/client'
import { outcomes } from '@/lib/labels'
import { cn } from '@/lib/utils'

export const outcomeColors = {
  APPROVE: '#059669', HOLD: '#d97706', RETURN: '#0284c7', REJECT: '#e11d48',
} satisfies Record<Schemas['Outcome'], string>

const tones = { APPROVE: 'text-approve', HOLD: 'text-hold', RETURN: 'text-return', REJECT: 'text-reject' }

export function StatusSquare({ outcome, className }: { outcome?: Schemas['Outcome'] | null; className?: string }) {
  return <span aria-hidden="true" className={cn('inline-block size-2 shrink-0', !outcome && 'border border-input', className)}
    style={outcome ? { backgroundColor: outcomeColors[outcome] } : undefined} />
}

const compactLabels = { APPROVE: 'Approved', HOLD: 'On hold', RETURN: 'Returned', REJECT: 'Rejected' }

export function OutcomeBadge({ outcome, compact = false }: { outcome: Schemas['Outcome'] | null | undefined; compact?: boolean }) {
  if (!outcome) return <span className="status-chip text-muted-foreground"><StatusSquare />Pending</span>
  return <span className={cn('status-chip', tones[outcome])}><StatusSquare outcome={outcome} />{compact ? compactLabels[outcome] : outcomes[outcome]}</span>
}
