import { pct } from '@/lib/format'

export function LedgerBar({ ordered, received, billed, twoWay = false }: {
  ordered: string; received: string; billed: string; twoWay?: boolean
}) {
  const total = Math.max(0, Number(ordered) || 0)
  const paid = Math.min(total, Math.max(0, Number(billed) || 0))
  const available = Math.min(total - paid, Math.max(0, Number(received) - paid || 0))
  const segments = twoWay
    ? [['Billed', paid, 'bg-indigo-600'], ['Remaining to bill', total - paid, 'bg-slate-200']] as const
    : [['Billed', paid, 'bg-indigo-600'], ['Received, unbilled', available, 'bg-sky-400'],
      ['Not received', total - paid - available, 'bg-slate-200']] as const
  const legend = segments.map(([label, quantity, color]) => ({
    label, quantity, color, ratio: total ? quantity / total : 0,
  }))
  return <div className="space-y-2">
    <div className="flex h-3 overflow-hidden rounded-full bg-slate-100" role="img"
      aria-label={legend.map(({ label, quantity, ratio }) => `${label} ${quantity} (${pct(ratio)})`).join(', ')}>
      {legend.map(({ label, quantity, ratio, color }) => <span key={label} title={`${label} ${quantity}`}
        className={color} style={{ width: `${Number((ratio * 100).toFixed(8))}%` }} />)}
    </div>
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden="true">
      {legend.map(({ label, quantity, color }) => <li key={label} className="flex items-center gap-1.5">
        <span className={`size-2.5 shrink-0 rounded-sm ${color}`} />{label}
        <span className="font-medium text-slate-800 tabular-nums">{quantity}</span>
      </li>)}
    </ul>
  </div>
}
