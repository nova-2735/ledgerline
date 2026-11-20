import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type Schemas } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { inr, istDate, pct } from '@/lib/format'

type Order = Schemas['PurchaseOrderOut']

function orderStatus(order: Order) {
  if (order.status === 'cancelled') return 'Cancelled'
  if (Number(order.pct_billed) >= 100) return 'Fully billed'
  return order.status === 'closed' ? 'Closed' : 'Open'
}

export function PurchaseOrders() {
  const [search, setSearch] = useState('')
  const orders = useQuery({ queryKey: queryKeys.orders, queryFn: ({ signal }) => api.purchaseOrders({}, signal) })
  const vendors = useQuery({ queryKey: queryKeys.vendors, queryFn: ({ signal }) => api.vendors(signal) })
  const names = new Map(vendors.data?.map(vendor => [vendor.vendor_id, vendor.legal_name]))
  const term = search.trim().toLowerCase()
  const rows = orders.data?.filter(order =>
    [order.po_number, names.get(order.vendor_id), order.vendor_id].some(text => text?.toLowerCase().includes(term)),
  )
  return <div className="space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="page-title">Purchase orders</h1>
        <p className="mt-1 text-sm text-muted-foreground">Review ordered value, invoices billed and quantities still available.</p>
      </div>
      <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute top-2 left-2 size-4 text-slate-500" />
        <Input aria-label="Search purchase orders" placeholder="Search PO or vendor" className="w-64 bg-white pl-8"
          value={search} onChange={event => setSearch(event.target.value)} />
      </div>
    </header>
    {orders.isError && <ErrorState title="Could not load purchase orders" error={orders.error} retry={() => void orders.refetch()} />}
    {vendors.isError && <ErrorState title="Could not load vendor names" error={vendors.error} retry={() => void vendors.refetch()} />}
    <section className="panel">
      {orders.isPending && <LoadingState label="Loading purchase orders" />}
      {rows?.length === 0 && <EmptyState title={search ? 'No matching purchase orders' : 'No purchase orders yet'} />}
      {!!rows?.length && <Table>
        <TableHeader className="bg-slate-50"><TableRow>
          {['PO', 'Vendor', 'Ordered on', 'Match', 'Ordered value', 'Billed value', '% billed', 'Status'].map((label, index) =>
            <TableHead key={label} className={index === 4 || index === 5 ? 'text-right' : undefined}>{label}</TableHead>)}
        </TableRow></TableHeader>
        <TableBody>{rows.map(order => {
          const fraction = Number(order.pct_billed) / 100
          const status = orderStatus(order)
          return <TableRow key={order.po_number} className="hover:bg-indigo-50/50">
            <TableCell><Link to={encodeURIComponent(order.po_number)} className="font-medium text-indigo-700 hover:underline">{order.po_number}</Link></TableCell>
            <TableCell>{names.get(order.vendor_id) ?? order.vendor_id}</TableCell>
            <TableCell className="tabular-nums">{istDate(order.po_date)}</TableCell>
            <TableCell>{order.match_type === 'three_way' ? 'Three-way' : 'Two-way'}</TableCell>
            <TableCell className="text-right font-medium tabular-nums">{inr(order.ordered_value)}</TableCell>
            <TableCell className="text-right tabular-nums">{inr(order.billed_value)}</TableCell>
            <TableCell><div className="flex min-w-28 items-center gap-2">
              <progress value={Math.max(0, Math.min(1, fraction || 0))} max={1} className="h-2 w-16 rounded accent-indigo-600"
                aria-label={`${order.po_number} billed`} />
              <span className="tabular-nums">{pct(fraction)}</span>
            </div></TableCell>
            <TableCell><span className={`status-chip ${status === 'Fully billed' ? 'bg-emerald-50 text-emerald-800' : 'bg-slate-100 text-slate-700'}`}>{status}</span></TableCell>
          </TableRow>
        })}</TableBody>
      </Table>}
    </section>
  </div>
}
