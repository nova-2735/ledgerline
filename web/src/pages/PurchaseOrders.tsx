import { useRef, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Schemas } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { LedgerBar, LedgerLegend } from '@/components/LedgerBar'
import { PageActions } from '@/components/layout/PageActions'
import { RowKeys } from '@/components/RowKeys'
import { SearchControl } from '@/components/SearchControl'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Button } from '@/components/ui/button'
import { inr, istDate, pct } from '@/lib/format'
import { rowIndex, useShortcuts } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

type Order = Schemas['PurchaseOrderOut']
const pageSize = 20

function orderStatus(order: Order) {
  if (order.status === 'cancelled') return 'Cancelled'
  if (Number(order.pct_billed) >= 100) return 'Fully billed'
  return order.status === 'closed' ? 'Closed' : 'Open'
}

function receivedValue(detail: Schemas['PurchaseOrderDetail']) {
  return detail.balances.reduce((total, row) => {
    const line = detail.po.lines.find(line => line.line_no === row.line_no)
    return total + Number(line?.unit_price ?? 0) * Math.min(Number(row.received), Number(row.ordered))
  }, 0).toFixed(2)
}

export function PurchaseOrders() {
  const input = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState('')
  const navigate = useNavigate()
  const orders = useQuery({ queryKey: queryKeys.orders, queryFn: ({ signal }) => api.purchaseOrders({}, signal) })
  const vendors = useQuery({ queryKey: queryKeys.vendors, queryFn: ({ signal }) => api.vendors(signal) })
  const names = new Map(vendors.data?.map(vendor => [vendor.vendor_id, vendor.legal_name]))
  const term = search.trim().toLowerCase()
  const rows = orders.data?.filter(order => [order.po_number, names.get(order.vendor_id), order.vendor_id].some(text => text?.toLowerCase().includes(term))) ?? []
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize))
  const currentPage = Math.min(page, pageCount - 1)
  const visible = rows.slice(currentPage * pageSize, (currentPage + 1) * pageSize)
  const active = visible.findIndex(row => row.po_number === selected)
  const progressOrders = visible.filter(row => row.match_type === 'three_way')
  const receiptQueries = useQueries({ queries: progressOrders.map(item => ({
    queryKey: ['purchase-order', item.po_number], queryFn: ({ signal }: { signal: AbortSignal }) => api.purchaseOrder(item.po_number, signal), staleTime: 60_000,
  })) })
  const details = new Map(progressOrders.map((row, i) => [row.po_number, receiptQueries[i]]))
  const path = (num: string) => '/purchase-orders/' + encodeURIComponent(num)
  function step(direction: 'next' | 'previous') {
    const order = visible[rowIndex(active, visible.length, direction)]
    if (order) { setSelected(order.po_number); document.getElementById('po-row-' + order.po_number)?.scrollIntoView?.({ block: 'nearest' }) }
  }
  function open() { if (active >= 0) void navigate(path(visible[active].po_number)) }
  useShortcuts({ search: () => input.current?.focus(), next: () => step('next'), previous: () => step('previous'), open, escape: () => setSelected('') })

  return <div className="page-padding flex h-full min-h-0 flex-col gap-3">
    <PageActions><SearchControl label="Search purchase orders" placeholder="Search PO or vendor…" inputRef={input} value={search} onChange={value => { setSearch(value); setPage(0) }} /></PageActions>
    {orders.isError && <ErrorState title="Could not load purchase orders" error={orders.error} retry={() => void orders.refetch()} />}
    {vendors.isError && <ErrorState title="Could not load vendor names" error={vendors.error} retry={() => void vendors.refetch()} />}
    <section className="panel flex min-h-0 flex-1 flex-col" aria-label="Purchase order ledger">
      <header className="panel-title shrink-0"><h2>Purchase order ledger</h2><LedgerLegend /></header>
      <div className="min-h-0 flex-1 overflow-auto">
        {orders.isPending ? <LoadingState label="Loading purchase orders" /> : !rows.length ?
          <EmptyState title={search ? 'No matching purchase orders' : 'No purchase orders yet'} /> :
          <table className="w-full min-w-[930px] table-fixed" aria-label="Purchase orders">
            <colgroup><col className="w-[113px]" /><col /><col className="w-[95px]" /><col className="w-[85px]" /><col className="w-[114px]" />
              <col className="w-[110px]" /><col className="w-[160px]" /><col className="w-[91px]" /></colgroup>
            <thead className="table-head"><tr>
              {['PO', 'Vendor', 'Ordered on', 'Match', 'Ordered value', 'Billed value', 'Ledger · % billed', 'Status'].map((label, index) =>
                <th key={label} scope="col" className={cn('px-2 font-medium', (index === 4 || index === 5) && 'text-right')}>{label}</th>)}
            </tr></thead>
            <tbody>{visible.map(order => {
              const data = details.get(order.po_number)
              const twoWay = order.match_type === 'two_way'
              const received = twoWay ? order.billed_value : data?.data && receivedValue(data.data)
              const status = orderStatus(order)
              return <tr id={'po-row-' + order.po_number} key={order.po_number} className={cn('table-row cursor-pointer hover:bg-muted', order.po_number === selected && 'bg-accent hover:bg-accent')}
                onClick={event => { if (!(event.target as Element).closest('a, button')) setSelected(order.po_number) }}
                onDoubleClick={event => { if (!(event.target as Element).closest('a, button')) void navigate(path(order.po_number)) }}>
                <td className="identifier px-2"><Link to={path(order.po_number)} className="text-link">{order.po_number}</Link></td>
                <td className="truncate px-2 font-medium" title={names.get(order.vendor_id)}>{names.get(order.vendor_id) ?? order.vendor_id}</td>
                <td className="px-2 text-meta text-muted-foreground">{istDate(order.po_date)}</td>
                <td className="px-2 text-meta text-muted-foreground">{twoWay ? 'Two-way' : 'Three-way'}</td>
                <td className="px-2 text-right">{inr(order.ordered_value)}</td>
                <td className="px-2 text-right">{inr(order.billed_value)}</td>
                <td className="px-2"><div className="grid grid-cols-[minmax(0,1fr)_4ch] items-center gap-2">
                  {received !== undefined ? <LedgerBar ordered={order.ordered_value} received={received} billed={order.billed_value} twoWay={twoWay} compact
                    format={value => inr(value.toFixed(2))} /> : <div className="h-1.5 bg-border" title={data?.isError ? 'Could not load receipts' : 'Loading receipts'} />}
                  <span className="text-right text-meta">{pct(Number(order.pct_billed) / 100)}</span>
                </div></td>
                <td className="px-2 text-meta"><span className={cn('status-chip', status === 'Fully billed' ? 'text-approve' : 'text-muted-foreground')}>
                  <span aria-hidden="true" className={cn('size-2 shrink-0', status === 'Fully billed' ? 'bg-approve' : 'border border-input')} />{status}
                </span></td>
              </tr>
            })}</tbody>
          </table>}
      </div>
      <footer className="flex min-h-9 shrink-0 items-center gap-2 border-t px-2 text-meta text-muted-foreground">
        <span>{rows.length ? 'Showing ' + (currentPage * pageSize + 1) + '–' + Math.min(rows.length, (currentPage + 1) * pageSize) + ' of ' + rows.length : 'Showing 0 purchase orders'}</span>
        <div className="ml-auto flex items-center gap-1">
          <RowKeys onStep={step} disabled={!visible.length} />
          <Button variant="ghost" size="sm" disabled={active < 0} onClick={open}>Open <ShortcutHint id="open" /></Button>
          <Button variant="ghost" size="icon-sm" aria-label="Previous page" disabled={!currentPage} onClick={() => setPage(currentPage - 1)}><ChevronLeft /></Button>
          <span>{currentPage + 1} / {pageCount}</span>
          <Button variant="ghost" size="icon-sm" aria-label="Next page" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}><ChevronRight /></Button>
        </div>
      </footer>
    </section>
  </div>
}
