import { Link, useNavigate } from 'react-router-dom'
import type { Schemas } from '@/api/client'
import { duration, inr, istDate, istTime } from '@/lib/format'
import { reasons } from '@/lib/labels'
import { EmptyState } from './EmptyState'
import { OutcomeBadge } from './OutcomeBadge'
import { SourceBadge } from './SourceBadge'
import { RunStatusChip } from './StatusChip'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table'

export function RunsTable({ runs }: { runs: Schemas['RunSummary'][] }) {
  const navigate = useNavigate()
  if (!runs.length) return <EmptyState title="No invoice runs found">Try a different search or filter.</EmptyState>

  return <Table>
    <TableHeader className="bg-slate-50">
      <TableRow className="hover:bg-transparent">
        {['Received', 'Source', 'Vendor', 'Invoice #', 'Amount', 'PO', 'Outcome', 'Reason', 'Status', 'Time'].map(label =>
          <TableHead key={label} className={`h-9 px-3 text-xs text-slate-600 ${label === 'Amount' || label === 'Time' ? 'text-right' : ''}`}>
            {label}
          </TableHead>,
        )}
      </TableRow>
    </TableHeader>
    <TableBody>
      {runs.map(run => <TableRow key={run.id} className="cursor-pointer hover:bg-indigo-50/50"
        onClick={event => { if (!(event.target as HTMLElement).closest('a')) void navigate(`/runs/${run.id}`) }}>
        <TableCell className="px-3 py-2 text-xs tabular-nums">
          <div>{istDate(run.created_at)}</div>
          <div className="text-muted-foreground">{istTime(run.created_at)}</div>
        </TableCell>
        <TableCell className="px-3"><SourceBadge source={run.source} /></TableCell>
        <TableCell className="max-w-48 truncate px-3 font-medium" title={run.vendor_name ?? undefined}>{run.vendor_name ?? '—'}</TableCell>
        <TableCell className="px-3 tabular-nums">
          <Link className="font-medium text-indigo-700 hover:underline" to={`/runs/${run.id}`}>
            {run.invoice_number ?? run.display_id}
          </Link>
        </TableCell>
        <TableCell className="px-3 text-right font-medium tabular-nums">{inr(run.total)}</TableCell>
        <TableCell className="px-3 tabular-nums">{run.po_number ?? '—'}</TableCell>
        <TableCell className="px-3"><OutcomeBadge outcome={run.final_outcome ?? run.outcome} /></TableCell>
        <TableCell className="max-w-40 truncate px-3 text-xs text-muted-foreground" title={run.primary_reason ? reasons[run.primary_reason] : undefined}>
          {run.primary_reason ? reasons[run.primary_reason] : '—'}
        </TableCell>
        <TableCell className="px-3"><RunStatusChip status={run.status} /></TableCell>
        <TableCell className="px-3 text-right text-muted-foreground tabular-nums">{duration(run.duration_ms)}</TableCell>
      </TableRow>)}
    </TableBody>
  </Table>
}
