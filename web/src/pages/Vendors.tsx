import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { PageActions } from '@/components/layout/PageActions'
import { RowKeys } from '@/components/RowKeys'
import { SearchControl } from '@/components/SearchControl'
import { maskedBank } from '@/lib/format'
import { rowIndex, useShortcuts } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

export function Vendors() {
  const [search, setSearch] = useState('')
  const [active, setActive] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const vendors = useQuery({ queryKey: queryKeys.vendors, queryFn: ({ signal }) => api.vendors(signal) })
  const term = search.trim().toLowerCase()
  const rows = vendors.data?.filter(vendor => [vendor.legal_name, vendor.gstin, vendor.vendor_id].some(value => value.toLowerCase().includes(term))) ?? []
  function step(direction: 'next' | 'previous') {
    const row = rows[rowIndex(rows.findIndex(row => row.vendor_id === active), rows.length, direction)]
    if (row) { setActive(row.vendor_id); document.getElementById('vendor-row-' + row.vendor_id)?.scrollIntoView?.({ block: 'nearest' }) }
  }
  useShortcuts({ search: () => input.current?.focus(), next: () => step('next'), previous: () => step('previous'), escape: () => setActive('') })

  return <div className="page-padding">
    <PageActions>
      <SearchControl label="Search vendors" placeholder="Search vendor or GSTIN…" inputRef={input} value={search} onChange={setSearch} />
      <RowKeys onStep={step} disabled={!rows.length} />
    </PageActions>
    {vendors.isError && <ErrorState title="Could not load vendor records" error={vendors.error} retry={() => void vendors.refetch()} />}
    <section className="panel flex min-h-0 flex-col" aria-label="Vendor master">
      <header className="panel-title"><h2>Vendor master</h2><span className="text-meta font-normal text-muted-foreground">{rows.length} records</span></header>
      {vendors.isPending ? <LoadingState label="Loading vendor records" /> :
        !rows.length ? <EmptyState title={search ? 'No matching vendors' : 'No vendor records'} /> :
        <div className="max-h-[calc(100dvh-152px)] overflow-auto">
          <table className="w-full min-w-[1080px] table-fixed" aria-label="Vendor records">
            <colgroup><col className="w-[50px]" /><col /><col className="w-[138px]" /><col className="w-[42px]" /><col className="w-[215px]" />
              <col className="w-[144px]" /><col className="w-[119px]" /><col className="w-[166px]" /><col className="w-[66px]" /><col className="w-[63px]" /></colgroup>
            <thead className="table-head"><tr>
              {['ID', 'Vendor name', 'GSTIN', 'State', 'Status', 'Bank on file', 'Phone on file', 'Email on file', 'Open POs', 'Invoices'].map((label, index) =>
                <th key={label} scope="col" className={cn('px-2 font-medium whitespace-nowrap', index >= 8 && 'text-right')}>{label}</th>)}
            </tr></thead>
            <tbody>{rows.map(vendor => {
              const blocked = vendor.status === 'blocked'
              return <tr key={vendor.vendor_id} id={'vendor-row-' + vendor.vendor_id} className={cn('table-row hover:bg-muted', active === vendor.vendor_id && 'bg-accent hover:bg-accent')}
                onClick={() => setActive(vendor.vendor_id)}>
                <td className="identifier px-2 text-muted-foreground">{vendor.vendor_id}</td>
                <td className="truncate px-2 font-medium" title={vendor.legal_name}>{vendor.legal_name}</td>
                <td className="identifier px-2">{vendor.gstin}</td>
                <td className="px-2 text-meta text-muted-foreground">{vendor.state_code}</td>
                <td className="px-2 text-meta">
                  <div className="flex min-w-0 items-center gap-1.5" title={vendor.block_reason ?? undefined}>
                    <span className={cn('size-2 shrink-0', blocked ? 'bg-reject' : 'bg-approve')} aria-hidden="true" />
                    <span className={cn('shrink-0 font-medium', blocked ? 'text-reject' : 'text-muted-foreground')}>{blocked ? 'Blocked' : 'Active'}</span>
                    </div>
                  {blocked && <span className="block leading-4 text-muted-foreground" title={vendor.block_reason ?? undefined}>{vendor.block_reason ?? 'Blocked from payment'}</span>}
                </td>
                <td className="px-2 text-meta"><span className="block truncate leading-4" title={vendor.bank_name}>{vendor.bank_name}</span><span className="identifier block leading-4 text-muted-foreground">{maskedBank(vendor.bank_account_number)}</span></td>
                <td className="truncate px-2 text-meta text-muted-foreground" title={vendor.phone_on_file}>{vendor.phone_on_file}</td>
                <td className="truncate px-2 text-meta text-muted-foreground" title={vendor.email}>{vendor.email}</td>
                <td className="px-2 text-right">{vendor.open_po_count}</td><td className="px-2 text-right">{vendor.invoice_count}</td>
              </tr>
            })}</tbody>
          </table>
        </div>}
    </section>
  </div>
}
