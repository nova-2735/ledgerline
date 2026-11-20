import { ArrowDown, ArrowUp, ArrowUpDown, ChevronRight } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { ShortcutHint } from '@/components/ShortcutHint'
import { duration, inr, istDate, istTime, relativeTime } from '@/lib/format'
import { reasons, routes, sources } from '@/lib/labels'
import { effectiveOutcome, type Run } from '@/lib/runList'
import { cn } from '@/lib/utils'
import { EmptyState } from './EmptyState'
import { OutcomeBadge } from './OutcomeBadge'
import { RunStatusChip } from './StatusChip'

export const runColumns = [
  ['outcome', 'Outcome'], ['display_id', 'Run'], ['created_at', 'Received'], ['vendor_name', 'Vendor'],
  ['invoice_number', 'Invoice #'], ['po_number', 'PO'], ['total', 'Amount'], ['primary_reason', 'Reason'],
  ['route', 'Owner'], ['duration_ms', 'Time'],
] as const
export type RunColumn = typeof runColumns[number][0]
export type RunSort = { column: RunColumn; ascending: boolean }
const collator = new Intl.Collator('en-IN', { numeric: true, sensitivity: 'base' })

export function sortRuns(runs: Run[], sort: RunSort) {
  function value(run: Run) {
    if (sort.column === 'outcome') return effectiveOutcome(run)
    if (sort.column === 'primary_reason') return run.primary_reason && reasons[run.primary_reason]
    if (sort.column === 'route') return run.route && routes[run.route]
    return run[sort.column]
  }
  return [...runs].sort((a, b) => {
    const x = value(a), y = value(b)
    if (x == null) return y == null ? b.id - a.id : 1
    if (y == null) return -1
    const result = sort.column === 'total' || sort.column === 'duration_ms' ? Number(x) - Number(y) : collator.compare(String(x), String(y))
    return (sort.ascending ? result : -result) || b.id - a.id
  })
}

type Selection = {
  activeId?: number
  checked: Set<number>
  activate: (id: number) => void
  toggle: (id: number) => void
  peek: (id: number) => void
}

export function RunsTable({ runs, sort, onSort, selection, now }: {
  runs: Run[]; sort?: RunSort; onSort?: (column: RunColumn) => void; selection?: Selection; now?: number
}) {
  const navigate = useNavigate()
  if (!runs.length) return <EmptyState title="No invoice runs found">Try a different search or filter.</EmptyState>

  return <table aria-label="Invoice runs" className="w-full min-w-[940px] table-fixed text-body">
    <colgroup>
      {selection && <col className="w-8" />}
      <col className="w-[134px]" /><col className="w-[77px]" /><col className="w-[93px]" />
      <col /><col className="w-[134px]" /><col className="w-[106px]" /><col className="w-[115px]" />
      <col /><col className="w-[100px]" /><col className="w-[59px]" />
      {selection && <col className="w-9" />}
    </colgroup>
    <thead className="table-head"><tr>
      {selection && <th className="px-2" scope="col"><ShortcutHint id="select" /><span className="sr-only">Export selection</span></th>}
      {runColumns.map(([column, label]) => {
        const current = sort?.column === column
        const Arrow = current ? (sort.ascending ? ArrowUp : ArrowDown) : ArrowUpDown
        const numeric = column === 'total' || column === 'duration_ms'
        return <th key={column} scope="col" className={cn('px-2.5 font-medium', numeric && 'text-right')}
          aria-sort={current ? (sort.ascending ? 'ascending' : 'descending') : undefined}>
          {onSort ? <button type="button" onClick={() => onSort(column)} className="inline-flex items-center gap-1 whitespace-nowrap hover:text-foreground">
            {label}<Arrow aria-hidden="true" className={cn('size-3 shrink-0', current ? 'text-primary' : 'text-faint')} />
          </button> : label}
        </th>
      })}
      {selection && <th scope="col"><span className="sr-only">Peek</span></th>}
    </tr></thead>
    <tbody>
      {runs.map(run => {
        const active = selection?.activeId === run.id
        const outcome = effectiveOutcome(run)
        const reason = run.primary_reason ? reasons[run.primary_reason] : null
        return <tr key={run.id} id={selection ? 'run-row-' + run.id : undefined} data-active={active || undefined}
          className={cn('table-row cursor-pointer hover:bg-muted', active && 'bg-accent hover:bg-accent')}
          onClick={event => {
            if ((event.target as Element).closest('a, button, input')) return
            if (selection) selection.activate(run.id)
            else void navigate('/runs/' + run.id)
          }}
          onDoubleClick={event => { if (!(event.target as Element).closest('a, button, input')) void navigate('/runs/' + run.id) }}>
          {selection && <td className="px-2"><input type="checkbox" className="size-3.5 align-middle accent-primary"
            aria-label={'Select ' + run.display_id + ' for export'} checked={selection.checked.has(run.id)}
            onChange={() => selection.toggle(run.id)} /></td>}
          <td className="px-2.5">{outcome ? <OutcomeBadge outcome={outcome} /> : <RunStatusChip status={run.status} />}</td>
          <td className="px-2.5"><Link className="identifier text-link" title={sources[run.source]} to={'/runs/' + run.id}>{run.display_id}</Link></td>
          <td className="truncate px-2.5 text-meta text-muted-foreground" title={istDate(run.created_at) + ' · ' + istTime(run.created_at)}>
            {relativeTime(run.created_at, now)}
          </td>
          <td className="truncate px-2.5 font-medium" title={run.vendor_name ?? undefined}>{run.vendor_name ?? '—'}</td>
          <td className="identifier truncate px-2.5" title={run.invoice_number ?? undefined}>{run.invoice_number ?? '—'}</td>
          <td className="identifier truncate px-2.5">{run.po_number ?
            <Link className="text-link" to={'/purchase-orders/' + encodeURIComponent(run.po_number)} title={run.po_number}>{run.po_number}</Link> : '—'}</td>
          <td className="px-2.5 text-right font-medium">{inr(run.total)}</td>
          <td className="truncate px-2.5 text-meta text-muted-foreground" title={reason ?? undefined}>{reason ?? '—'}</td>
          <td className="truncate px-2.5 text-meta text-muted-foreground" title={run.route && routes[run.route] || undefined}>{run.route && run.route !== 'none' ? routes[run.route] : '—'}</td>
          <td className="px-2.5 text-right text-meta text-muted-foreground">{duration(run.duration_ms)}</td>
          {selection && <td><button type="button" aria-label={'Peek ' + run.display_id} title="Peek (Space)" onClick={() => selection.peek(run.id)}
            className="grid size-7 place-items-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground">
            <ChevronRight aria-hidden="true" className="size-4" /></button></td>}
        </tr>
      })}
    </tbody>
  </table>
}
