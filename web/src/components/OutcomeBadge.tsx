import { CheckCircle2, Clock3, CornerUpLeft, XCircle } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { outcomes } from '@/lib/labels'
import { cn } from '@/lib/utils'

export const outcomeColors = {
  APPROVE: '#059669', HOLD: '#d97706', RETURN: '#0284c7', REJECT: '#e11d48',
} satisfies Record<Schemas['Outcome'], string>

const styles = {
  APPROVE: [CheckCircle2, 'bg-emerald-50 text-emerald-800'],
  HOLD: [Clock3, 'bg-amber-50 text-amber-900'],
  RETURN: [CornerUpLeft, 'bg-sky-50 text-sky-800'],
  REJECT: [XCircle, 'bg-rose-50 text-rose-800'],
} as const

export function OutcomeBadge({ outcome }: { outcome: Schemas['Outcome'] | null | undefined }) {
  if (!outcome) return <span className="text-muted-foreground">—</span>
  const [Icon, color] = styles[outcome]
  return <span className={cn('status-chip', color)}><Icon aria-hidden="true" />{outcomes[outcome]}</span>
}
