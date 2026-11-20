import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, Search, ShieldX } from 'lucide-react'
import { api } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { maskedBank } from '@/lib/format'

export function Vendors() {
  const [search, setSearch] = useState('')
  const vendors = useQuery({ queryKey: queryKeys.vendors, queryFn: ({ signal }) => api.vendors(signal) })
  const term = search.trim().toLowerCase()
  const rows = vendors.data?.filter(vendor => [vendor.legal_name, vendor.gstin, vendor.vendor_id].some(value => value.toLowerCase().includes(term)))
  return <div className="space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="page-title">Vendors</h1>
        <p className="mt-1 text-sm text-muted-foreground">View the vendor records used to check invoice, contact and payment details.</p>
      </div>
      <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute top-2 left-2 size-4 text-slate-500" />
        <Input aria-label="Search vendors" placeholder="Search vendor or GSTIN" className="w-64 bg-white pl-8"
          value={search} onChange={event => setSearch(event.target.value)} />
      </div>
    </header>
    {vendors.isError && <ErrorState title="Could not load vendor records" error={vendors.error} retry={() => void vendors.refetch()} />}
    <section className="panel">
      {vendors.isPending && <LoadingState label="Loading vendor records" />}
      {rows?.length === 0 && <EmptyState title={search ? 'No matching vendors' : 'No vendor records'} />}
      {!!rows?.length && <Table>
        <TableHeader className="bg-slate-50"><TableRow>
          {['ID', 'Vendor name', 'GSTIN', 'State code', 'Status', 'Bank on file', 'Phone on file', 'Email on file', 'Open POs', 'Invoices']
            .map((label, index) => <TableHead key={label} className={index >= 8 ? 'text-right' : undefined}>{label}</TableHead>)}
        </TableRow></TableHeader>
        <TableBody>{rows.map(vendor => <TableRow key={vendor.vendor_id}>
          <TableCell className="text-muted-foreground tabular-nums">{vendor.vendor_id}</TableCell>
          <TableCell className="max-w-52 whitespace-normal font-medium">{vendor.legal_name}</TableCell>
          <TableCell className="tabular-nums">{vendor.gstin}</TableCell>
          <TableCell className="tabular-nums">{vendor.state_code}</TableCell>
          <TableCell>{vendor.status === 'blocked' ? <Tooltip>
            <TooltipTrigger asChild><button type="button" className="status-chip cursor-help bg-rose-50 text-rose-800">
              <ShieldX aria-hidden="true" />Blocked
            </button></TooltipTrigger>
            <TooltipContent className="max-w-64">{vendor.block_reason ?? 'This vendor is blocked from payment.'}</TooltipContent>
          </Tooltip> : <span className="status-chip bg-emerald-50 text-emerald-800"><Check aria-hidden="true" />Active</span>}</TableCell>
          <TableCell><span>{vendor.bank_name}</span><span className="block text-xs text-muted-foreground tabular-nums">{maskedBank(vendor.bank_account_number)}</span></TableCell>
          <TableCell className="tabular-nums">{vendor.phone_on_file}</TableCell>
          <TableCell>{vendor.email}</TableCell>
          <TableCell className="text-right tabular-nums">{vendor.open_po_count}</TableCell>
          <TableCell className="text-right tabular-nums">{vendor.invoice_count}</TableCell>
        </TableRow>)}</TableBody>
      </Table>}
    </section>
  </div>
}
