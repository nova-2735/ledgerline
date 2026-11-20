import { useQueries, useQuery } from '@tanstack/react-query'
import { ArrowLeft, ClipboardList } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { api, type Schemas } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { LedgerBar } from '@/components/LedgerBar'
import { RunsTable } from '@/components/RunsTable'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { inr, istDate } from '@/lib/format'

export function PoDetail() {
  const { po: number = '' } = useParams()
  const order = useQuery({
    queryKey: ['purchase-order', number],
    queryFn: ({ signal }) => api.purchaseOrder(number, signal),
    enabled: Boolean(number),
  })
  const vendors = useQuery({ queryKey: queryKeys.vendors, queryFn: ({ signal }) => api.vendors(signal) })
  const billedIds = [...new Set(order.data?.balances.flatMap(balance => balance.invoices) ?? [])]
  const invoiceQueries = useQueries({
    queries: billedIds.map(id => ({ queryKey: queryKeys.run(id), queryFn: ({ signal }) => api.getRun(id, signal) })),
  })
  const invoices = new Map(invoiceQueries.flatMap(query => query.data ? [[query.data.id, query.data] as const] : []))
  const vendor = vendors.data?.find(item => item.vendor_id === order.data?.po.vendor_id)
  return <div className="space-y-4">
    <Link to="/purchase-orders" className="inline-flex items-center gap-1.5 text-sm font-medium text-indigo-700 hover:underline">
      <ArrowLeft className="size-4" aria-hidden="true" />Purchase orders
    </Link>
    <header>
      <h1 className="page-title">{number || 'Purchase order'}</h1>
      {order.data && <p className="mt-1 text-sm text-muted-foreground">
        {vendor?.legal_name ?? order.data.po.vendor_id} · {order.data.po.buyer_name} · {istDate(order.data.po.po_date)}
        {' · '}{order.data.po.match_type === 'three_way' ? 'Three-way match' : 'Two-way match'}
      </p>}
    </header>
    {order.isPending && <div className="panel"><LoadingState label="Loading purchase order" /></div>}
    {order.isError && <ErrorState title="Could not load the purchase order" error={order.error} retry={() => void order.refetch()} />}
    {order.data && <PurchaseLedger data={order.data} invoices={invoices} />}
  </div>
}

function PurchaseLedger({ data, invoices }: { data: Schemas['PurchaseOrderDetail']; invoices: Map<number, Schemas['RunDetail']> }) {
  const { po, balances, grns, runs } = data
  return <>
    <section className="space-y-3">
      <h2 className="section-title flex items-center gap-2"><ClipboardList aria-hidden="true" className="size-4 text-indigo-700" />Line quantities</h2>
      {!po.lines.length && <div className="panel"><EmptyState title="No lines on this order" /></div>}
      {!!po.lines.length && <div className="grid gap-3 lg:grid-cols-2">
        {po.lines.map(line => {
          const balance = balances.find(item => item.line_no === line.line_no)
          const ordered = balance?.ordered ?? line.quantity
          const received = balance?.received
          const billed = balance?.billed
          const remaining = balance?.remaining_to_bill
          return <article className="panel min-w-0 space-y-3 p-4" key={line.line_no}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 className="section-title">{line.description}</h3>
                <p className="text-xs text-muted-foreground">Line {line.line_no} · {line.item_code}</p>
              </div>
              <span className="text-sm font-medium tabular-nums">{inr(line.unit_price)} / {line.uom}</span>
            </div>
            <dl className="grid grid-cols-2 gap-2 rounded-lg bg-slate-50 px-3 py-2.5 sm:grid-cols-4">
              {([['Ordered', ordered], ['Received', received], ['Billed', billed], ['Remaining to bill', remaining]] as const)
                .map(([label, quantity]) => <div key={label}>
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="font-semibold tabular-nums">{quantity ?? '—'}</dd>
                </div>)}
            </dl>
            {balance && <LedgerBar ordered={balance.ordered} received={balance.received} billed={balance.billed} twoWay={po.match_type === 'two_way'} />}
            {!!balance?.invoices.length && <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t pt-2 text-sm">
              <span className="text-muted-foreground">Billed invoices</span>
              {balance.invoices.map(id => {
                const run = invoices.get(id)
                const linked = run ?? runs.find(item => item.id === id)
                const match = run?.matching?.rows.find(row => row.po_line_nos.length === 1 && row.po_line_nos[0] === line.line_no)
                return <Link key={id} to={`/runs/${id}`} className="rounded-md bg-indigo-50 px-2 py-1 font-medium text-indigo-800 hover:underline">
                  {linked?.scenario_id ?? linked?.invoice_number ?? linked?.display_id ?? `Run ${id}`}
                  {match?.qty_invoiced && ` · ${match.qty_invoiced} invoiced`}
                </Link>
              })}
            </div>}
          </article>
        })}
      </div>}
    </section>
    <section className="panel">
      <h2 className="section-title border-b px-4 py-3">Goods receipts</h2>
      {grns.length ? <Table>
        <TableHeader className="bg-slate-50"><TableRow>
          <TableHead>Receipt</TableHead><TableHead>Received on</TableHead><TableHead>PO line</TableHead><TableHead className="text-right">Quantity received</TableHead>
        </TableRow></TableHeader>
        <TableBody>{grns.map(receipt => <TableRow key={`${receipt.grn_number}-${receipt.line_no}`}>
          <TableCell className="font-medium">{receipt.grn_number}</TableCell><TableCell>{istDate(receipt.received_date)}</TableCell>
          <TableCell>{receipt.line_no}</TableCell><TableCell className="text-right tabular-nums">{receipt.quantity_received}</TableCell>
        </TableRow>)}</TableBody>
      </Table> : <EmptyState title="No goods receipts recorded">{po.match_type === 'two_way' && 'This order is matched against the invoice and purchase order.'}</EmptyState>}
    </section>
    <section className="panel">
      <h2 className="section-title border-b px-4 py-3">Invoices on this order</h2>
      {runs.length ? <RunsTable runs={runs} /> : <EmptyState title="No invoices on this order yet" />}
    </section>
  </>
}
