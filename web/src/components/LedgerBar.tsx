import { pct } from '@/lib/format'

export function LedgerBar({ ordered, received, billed, twoWay = false, compact = false, format = String }: {
  ordered: string; received: string; billed: string; twoWay?: boolean; compact?: boolean; format?: (quantity: number) => string
}) {
  const total = Math.max(0, Number(ordered) || 0)
  const paid = Math.min(total, Math.max(0, Number(billed) || 0))
  const available = Math.min(total - paid, Math.max(0, Number(received) - paid || 0))
  const segments = twoWay
    ? [['Billed', paid, 'bg-primary'], ['Remaining to bill', total - paid, 'bg-border']] as const
    : [['Billed', paid, 'bg-primary'], ['Received, unbilled', available, 'bg-faint'],
      ['Not received', total - paid - available, 'bg-border']] as const
  const legend = segments.map(([label, quantity, color]) => ({
    label, quantity: format(quantity), color, ratio: total ? quantity / total : 0,
  }))
  return <div className="space-y-1.5">
    <div className="flex h-1.5 w-full overflow-hidden bg-border" role="img"
      aria-label={legend.map(({ label, quantity, ratio }) => label + ' ' + quantity + ' (' + pct(ratio) + ')').join(', ')}>
      {legend.map(({ label, quantity, ratio, color }) => <span key={label} title={label + ' ' + quantity}
        className={color} style={{ width: Number((ratio * 100).toFixed(8)) + '%' }} />)}
    </div>
    {!compact && <ul className="flex flex-wrap gap-x-3 gap-y-1 text-meta text-muted-foreground" aria-hidden="true">
      {legend.map(({ label, quantity, color }) => <li key={label} className="flex items-center gap-1.5">
        <span className={'size-2 shrink-0 ' + color} />{label}<span className="font-medium text-foreground">{quantity}</span>
      </li>)}
    </ul>}
  </div>
}

export function LedgerLegend({ twoWay }: { twoWay?: boolean }) {
  return <div className="flex flex-wrap gap-x-3 gap-y-1 text-meta text-muted-foreground">
    <span className="flex items-center gap-1.5"><span className="size-2 bg-primary" />Billed</span>
    {!twoWay && <span className="flex items-center gap-1.5"><span className="size-2 bg-faint" />Received, unbilled</span>}
    <span className="flex items-center gap-1.5"><span className="size-2 bg-border" />{twoWay ? 'Remaining to bill' : 'Not received'}</span>
  </div>
}
