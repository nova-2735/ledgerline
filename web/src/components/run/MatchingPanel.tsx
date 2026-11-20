import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '@/api/client'
import { EmptyState } from '@/components/EmptyState'
import { StatusChip } from '@/components/StatusChip'
import { inr, istDate, pct } from '@/lib/format'
import { CandidateList } from './CandidateList'

function QuantityLedger({ row }: { row: Schemas['MatchRow'] }) {
  if (row.qty_ordered === null) return null
  const billed = Math.max(0, Number(row.qty_billed_before) || 0)
  const thisInvoice = Math.max(0, Number(row.qty_invoiced) || 0)
  const remaining = Math.max(0, Number(row.qty_ordered) - billed - thisInvoice)
  const portions = [
    ['Billed', billed, 'bg-slate-400'], ['This invoice', thisInvoice, 'bg-indigo-500'], ['Remaining', remaining, 'bg-slate-200'],
  ] as const
  const total = billed + thisInvoice + remaining
  if (!total) return null
  return <div className="space-y-1.5">
    <div className="flex h-2 overflow-hidden rounded-full" role="img" aria-label={portions.map(([label, quantity]) => `${label} ${quantity}`).join(', ')}>
      {portions.map(([label, quantity, tone]) => <span key={label} className={tone} style={{ width: `${quantity / total * 100}%` }} />)}
    </div>
    <div className="flex flex-wrap gap-2 text-xs text-muted-foreground" aria-hidden="true">
      {portions.map(([label, quantity, tone]) => <span key={label} className="flex items-center gap-1"><span className={`size-2 rounded-sm ${tone}`} />{label} {quantity}</span>)}
    </div>
  </div>
}

export function MatchingPanel({ run }: { run: Schemas['RunDetail'] }) {
  const match = run.matching
  const order = useQuery({
    queryKey: ['purchase-order', match?.po_number],
    queryFn: ({ signal }) => api.purchaseOrder(match!.po_number!, signal),
    enabled: Boolean(match?.po_number),
  })
  if (!match) return <EmptyState title="No purchase order match yet">Matching appears after the purchase order and invoice lines are checked.</EmptyState>
  const inferred = match.po_candidates.length > 0 && !run.review_actions.some(review => review.action === 'confirm_po')
  return <div className="space-y-3">
    <section className="space-y-2 rounded-lg border bg-slate-50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="section-title">{match.po_number
          ? <Link to={`/purchase-orders/${encodeURIComponent(match.po_number)}`} className="text-indigo-700 hover:underline">{match.po_number}</Link>
          : 'Purchase order'}</h3>
        <div className="flex flex-wrap gap-1">
          {match.match_type && <span className="status-chip bg-white text-slate-700">{match.match_type === 'three_way' ? 'Three-way match' : 'Two-way match'}</span>}
          {inferred && <span className="status-chip bg-amber-50 text-amber-900">Inferred</span>}
        </div>
      </div>
      {order.data && <p className="text-xs text-muted-foreground">{order.data.po.buyer_name} · {istDate(order.data.po.po_date)}</p>}
      <dl className="grid grid-cols-3 gap-2 border-t pt-2 text-sm tabular-nums">
        {([['Expected', match.header_expected], ['Invoiced', match.header_invoiced], ['Variance', match.header_variance]] as const)
          .map(([label, value]) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="font-medium">{inr(value)}</dd></div>)}
      </dl>
    </section>
    {match.rows.map((row, index) => <section key={index} className={`space-y-2 rounded-lg border p-3 ${row.kind === 'bundled' ? 'border-l-4 border-l-indigo-400' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{row.description_invoice ?? 'No invoice line'}</h3>
          <p className="text-xs text-muted-foreground">{row.description_po ?? 'No matching order line'}{row.po_line_nos.length ? ` · PO line ${row.po_line_nos.join(', ')}` : ''}</p>
          {row.kind === 'bundled' && <span className="status-chip bg-indigo-50 text-indigo-800">Bundled items</span>}
        </div>
        <StatusChip status={row.status} />
      </div>
      <dl className="grid grid-cols-3 gap-x-1 gap-y-2 rounded bg-slate-50 p-2 text-sm tabular-nums sm:grid-cols-5">
        {([['Invoiced', row.qty_invoiced], ['Ordered', row.qty_ordered], ['Received', row.qty_received],
          ['Billed before', row.qty_billed_before], ['Available', row.qty_available]] as const)
          .map(([label, value]) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="font-medium">{value ?? '—'}</dd></div>)}
      </dl>
      <div className="text-xs text-slate-700 tabular-nums">Unit price {inr(row.unit_price_invoice)} · Order price {inr(row.unit_price_po)}
        {row.price_variance_pct !== null && ` · ${pct(Number(row.price_variance_pct) / 100)} variance`}
      </div>
      <QuantityLedger row={row} />
    </section>)}
    <CandidateList candidates={match.po_candidates} />
  </div>
}
