import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '@/api/client'
import { EmptyState } from '@/components/EmptyState'
import { StatusChip } from '@/components/StatusChip'
import { inr, istDate, pct } from '@/lib/format'
import { cn } from '@/lib/utils'
import { CandidateList } from './CandidateList'

function QuantityLedger({ row }: { row: Schemas['MatchRow'] }) {
  if (row.qty_ordered === null) return null
  const billed = Math.max(0, Number(row.qty_billed_before) || 0)
  const thisInvoice = Math.max(0, Number(row.qty_invoiced) || 0)
  const remaining = Math.max(0, Number(row.qty_ordered) - billed - thisInvoice)
  const portions = [['Billed', billed, 'bg-faint'], ['This invoice', thisInvoice, 'bg-primary'], ['Remaining', remaining, 'bg-border']] as const
  const total = billed + thisInvoice + remaining
  if (!total) return null
  return <div className="mt-1 space-y-0.5">
    <div className="flex h-1.5 overflow-hidden" role="img" aria-label={portions.map(([label, quantity]) => label + ' ' + quantity).join(', ')}>
      {portions.map(([label, quantity, tone]) => <span key={label} className={tone} style={{ width: (quantity / total * 100) + '%' }} />)}
    </div>
    <div className="flex flex-wrap gap-2 text-meta text-muted-foreground" aria-hidden="true">
      {portions.map(([label, quantity, tone]) => <span key={label} className="flex items-center gap-1"><span className={cn('size-2', tone)} />{label} {quantity}</span>)}
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
    <section className="panel">
      <header className="panel-title">
        <h3>{match.po_number ? <Link to={'/purchase-orders/' + encodeURIComponent(match.po_number)} className="identifier text-link">{match.po_number}</Link> : 'Purchase order'}</h3>
        <div className="flex flex-wrap items-center gap-1.5 text-meta font-normal text-muted-foreground">
          {match.match_type && <span>{match.match_type === 'three_way' ? 'Three-way match' : 'Two-way match'}</span>}
          {inferred && <span className="rounded-sm border px-1 text-primary">Inferred</span>}
        </div>
      </header>
      {order.data && <p className="border-b px-2 py-1.5 text-meta text-muted-foreground">{order.data.po.buyer_name} · {istDate(order.data.po.po_date)}</p>}
      <dl className="grid grid-cols-3 divide-x text-right text-meta">
        {([['Expected', match.header_expected], ['Invoiced', match.header_invoiced], ['Variance', match.header_variance]] as const)
          .map(([label, value]) => <div key={label} className="px-2 py-1.5"><dt className="text-muted-foreground">{label}</dt><dd className="font-medium">{inr(value)}</dd></div>)}
      </dl>
    </section>
    {!!match.rows.length && <section className="panel">
      <h3 className="panel-title">Invoice and order lines</h3>
      <div className="overflow-auto">
        <table aria-label="Matching invoice lines" className="w-full min-w-[385px] table-fixed text-meta">
          <colgroup><col className="w-[46%]" /><col className="w-[26%]" /><col className="w-[28%]" /></colgroup>
          <thead className="table-head"><tr>
            <th scope="col" className="px-2 font-medium">Line match</th><th scope="col" className="px-2 text-right font-medium">Quantities</th><th scope="col" className="px-2 text-right font-medium">Unit price</th>
          </tr></thead>
          {match.rows.map((row, index) => <tbody key={index} className="border-b last:border-b-0">
            <tr className="min-h-9">
              <td className={cn('border-l-2 border-l-transparent px-2 py-1.5 align-top', row.kind === 'bundled' && 'border-l-primary')}>
                <div className="font-medium">{row.description_invoice ?? 'No invoice line'}</div>
                <div className="text-muted-foreground">{row.description_po ?? 'No matching order line'}</div>
                {!!row.po_line_nos.length && <div className="identifier text-muted-foreground">{row.kind === 'bundled' ? 'Bundle · ' : ''}PO {row.po_line_nos.join(', ')}</div>}
                <StatusChip status={row.status} />
              </td>
              <td className="px-2 py-1.5 align-top"><dl className="grid grid-cols-[1fr_auto] gap-x-1">
                {([['Invoiced', row.qty_invoiced], ['Ordered', row.qty_ordered], ['Received', row.qty_received], ['Billed', row.qty_billed_before], ['Available', row.qty_available]] as const)
                  .map(([label, value]) => <div key={label} className="contents"><dt className="text-muted-foreground">{label}</dt><dd className="text-right">{value ?? '—'}</dd></div>)}
              </dl></td>
              <td className="px-2 py-1.5 text-right align-top">
                <div title="Invoice unit price">{inr(row.unit_price_invoice)}</div>
                <div className="text-muted-foreground" title="Order unit price">{inr(row.unit_price_po)}</div>
                {row.price_variance_pct !== null && <div className="text-muted-foreground">{pct(Number(row.price_variance_pct) / 100)}</div>}
              </td>
            </tr>
            {row.qty_ordered !== null && <tr><td colSpan={3} className="px-2 pb-2"><QuantityLedger row={row} /></td></tr>}
          </tbody>)}
        </table>
      </div>
    </section>}
    <CandidateList candidates={match.po_candidates} />
  </div>
}
