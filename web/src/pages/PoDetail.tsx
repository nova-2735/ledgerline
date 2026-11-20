import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api, type Schemas } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { LedgerBar, LedgerLegend } from '@/components/LedgerBar'
import { PageActions } from '@/components/layout/PageActions'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { Panel } from '@/components/Panel'
import { inr, istDate } from '@/lib/format'
import { effectiveOutcome } from '@/lib/runList'

export function PoDetail() {
  const { po: number = '' } = useParams()
  const order = useQuery({
    queryKey: ['purchase-order', number], queryFn: ({ signal }) => api.purchaseOrder(number, signal), enabled: Boolean(number),
  })
  const vendors = useQuery({ queryKey: queryKeys.vendors, queryFn: ({ signal }) => api.vendors(signal) })
  const billedIds = [...new Set(order.data?.balances.flatMap(balance => balance.invoices) ?? [])]
  const details = useQueries({ queries: billedIds.map(id => ({ queryKey: queryKeys.run(id), queryFn: ({ signal }) => api.getRun(id, signal) })) })
  const invoices = new Map(details.flatMap(query => query.data ? [[query.data.id, query.data] as const] : []))
  const vendor = vendors.data?.find(item => item.vendor_id === order.data?.po.vendor_id)
  return <div className="page-padding">
    {order.data && <PageActions>
      <span className="hidden max-w-56 truncate text-meta font-medium sm:inline">{vendor?.legal_name ?? order.data.po.vendor_id}</span>
      <span className="hidden text-meta text-muted-foreground md:inline">{order.data.po.buyer_name} · {istDate(order.data.po.po_date)}</span>
      <span className="rounded-sm border bg-muted px-1.5 py-0.5 text-meta text-muted-foreground">{order.data.po.match_type === 'two_way' ? 'Two-way' : 'Three-way'}</span>
    </PageActions>}
    {order.isPending && <div className="panel"><LoadingState label="Loading purchase order" /></div>}
    {order.isError && <ErrorState title="Could not load the purchase order" error={order.error} retry={() => void order.refetch()} />}
    {order.data && <PurchaseLedger data={order.data} invoices={invoices} />}
  </div>
}

function Head({ labels, numeric = [] }: { labels: string[]; numeric?: number[] }) {
  return <thead className="table-head"><tr>{labels.map((label, index) =>
    <th key={label} scope="col" className={'px-2 font-medium ' + (numeric.includes(index) ? 'text-right' : '')}>{label}</th>)}</tr></thead>
}

function PurchaseLedger({ data, invoices }: { data: Schemas['PurchaseOrderDetail']; invoices: Map<number, Schemas['RunDetail']> }) {
  const { po, balances, grns, runs } = data
  const twoWay = po.match_type === 'two_way'
  return <div className="grid gap-px border bg-border lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
    <Panel title="Line balances" className="lg:row-span-2" action={<LedgerLegend twoWay={twoWay} />}>
      {!po.lines.length ? <EmptyState title="No lines on this order" /> :
      <div className="overflow-auto">
        <table className="w-full min-w-[490px] text-body" aria-label="Purchase order lines">
          <Head labels={['Line', 'Ordered', 'Received', 'Billed', 'Remaining']} numeric={[1, 2, 3, 4]} />
          {po.lines.map(line => {
            const balance = balances.find(item => item.line_no === line.line_no)
            const values = [balance?.ordered ?? line.quantity, balance?.received, balance?.billed, balance?.remaining_to_bill]
            return <tbody key={line.line_no} className="border-b last:border-b-0">
              <tr className="h-9">
                <td className="px-2 py-1.5"><p className="font-medium">{line.description}</p>
                  <p className="identifier text-muted-foreground">{line.line_no} · {line.item_code}</p></td>
                {values.map((value, index) => <td key={index} className="px-2 text-right text-meta whitespace-nowrap">{value ?? '—'}{value != null && ' ' + line.uom}</td>)}
              </tr>
              <tr><td colSpan={5} className="p-2 pt-0">
                <p className="mb-1 text-right text-meta text-muted-foreground">{inr(line.unit_price)} / {line.uom}</p>
                {balance && <LedgerBar ordered={balance.ordered} received={balance.received} billed={balance.billed} twoWay={twoWay} />}
                {!!balance?.invoices.length && <div className="mt-2 flex flex-wrap items-center gap-1.5 text-meta">
                  <span className="text-muted-foreground">Billed invoices</span>
                  {balance.invoices.map(id => {
                    const run = invoices.get(id)
                    const linked = run ?? runs.find(item => item.id === id)
                    const match = run?.matching?.rows.find(row => row.po_line_nos.length === 1 && row.po_line_nos[0] === line.line_no)
                    return <Link key={id} to={'/runs/' + id} className="text-link rounded-sm border px-1.5 py-0.5">
                      <span className="identifier">{linked?.scenario_id ?? linked?.invoice_number ?? linked?.display_id ?? 'R-' + String(id).padStart(4, '0')}</span>
                      {match?.qty_invoiced && ' · ' + match.qty_invoiced + ' ' + line.uom + ' invoiced'}
                    </Link>
                  })}
                </div>}
              </td></tr>
            </tbody>
          })}
        </table>
      </div>}
    </Panel>
    <Panel title="Goods receipts">
      {grns.length ? <div className="overflow-auto"><table className="w-full min-w-[330px]" aria-label="Goods receipts">
        <Head labels={['Receipt', 'Received on', 'PO line', 'Quantity received']} numeric={[2, 3]} />
        <tbody>{grns.map(receipt => <tr className="table-row" key={receipt.grn_number + '-' + receipt.line_no}>
          <td className="identifier px-2">{receipt.grn_number}</td><td className="px-2 text-meta">{istDate(receipt.received_date)}</td>
          <td className="px-2 text-right">{receipt.line_no}</td><td className="px-2 text-right">{receipt.quantity_received} {po.lines.find(line => line.line_no === receipt.line_no)?.uom}</td>
        </tr>)}</tbody>
      </table></div> : <EmptyState title="No goods receipts recorded">{twoWay && 'This order is matched directly to the invoice.'}</EmptyState>}
    </Panel>
    <Panel title="Invoices on this order">
      {runs.length ? <div className="overflow-auto"><table className="w-full min-w-[400px]" aria-label="Invoices on this order">
        <Head labels={['Run', 'Invoice #', 'Outcome', 'Amount']} numeric={[3]} />
        <tbody>{runs.map(run => <tr className="table-row hover:bg-muted" key={run.id}>
          <td className="identifier px-2"><Link className="text-link" to={'/runs/' + run.id}>{run.display_id}</Link></td>
          <td className="identifier px-2">{run.invoice_number ?? '—'}</td>
          <td className="px-2"><OutcomeBadge outcome={effectiveOutcome(run)} /></td><td className="px-2 text-right">{inr(run.total)}</td>
        </tr>)}</tbody>
      </table></div> : <EmptyState title="No invoices on this order yet" />}
    </Panel>
  </div>
}
