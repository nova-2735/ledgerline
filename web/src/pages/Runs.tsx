import { useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, Search, X } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAllRuns, useHealth } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { PageActions } from '@/components/layout/PageActions'
import { PeekDrawer } from '@/components/PeekDrawer'
import { RunsTable, runColumns, sortRuns, type RunColumn } from '@/components/RunsTable'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { outcomes, reasons, routes, runStatuses, sources } from '@/lib/labels'
import { dayOf, downloadRuns, effectiveOutcome, inView, runViews, type Run, type RunView } from '@/lib/runList'
import { rowIndex, useShortcuts } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

const pageSize = 50
const entries = (labels: Record<string, string>) => Object.entries(labels)

export function Runs() {
  const runs = useAllRuns(true)
  const today = useHealth().data?.health.today
  const now = today ? new Date(today + 'T23:59:59+05:30').getTime() : undefined
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const search = useRef<HTMLInputElement>(null)
  const [active, setActive] = useState<number>()
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [peek, setPeek] = useState<number | null>(null)
  const all = runs.data ?? []
  const view = (runViews.find(([id]) => id === params.get('view'))?.[0] ?? 'all') as RunView
  const query = params.get('q') ?? ''
  const column = runColumns.find(([name]) => name === params.get('sort'))?.[0] ?? 'created_at'
  const sort = { column, ascending: params.get('direction') === 'asc' }
  const filters = [
    { key: 'outcome', label: 'Outcome', options: entries(outcomes) },
    { key: 'owner', label: 'Owner', options: entries(routes) },
    { key: 'vendor', label: 'Vendor', options: Array.from(new Map(all.filter(r => r.vendor_name).map(r => [r.vendor_id ?? r.vendor_name!, r.vendor_name!])).entries()).sort((a, b) => a[1].localeCompare(b[1])) },
    { key: 'reason', label: 'Reason', options: entries(reasons) },
    { key: 'source', label: 'Source', options: entries(sources) },
    { key: 'status', label: 'Status', options: entries(runStatuses) },
  ]
  const value = (key: string) => params.get(key) ?? ''
  const date = value('date'), from = value('from'), to = value('to')
  const matches = all.filter(r => {
    const word = query.trim().toLowerCase()
    const found = !word || [r.display_id, r.invoice_number, r.po_number, r.vendor_name, r.scenario_id, r.subject, r.filename]
      .some(text => text?.toLowerCase().includes(word))
    const day = dayOf(r.created_at)
    return found && (!value('outcome') || value('outcome') === effectiveOutcome(r)) &&
      (!value('owner') || value('owner') === r.route) && (!value('vendor') || value('vendor') === (r.vendor_id ?? r.vendor_name)) &&
      (!value('reason') || value('reason') === r.primary_reason) && (!value('source') || value('source') === r.source) &&
      (!value('status') || value('status') === r.status) && (!date || date === day) && (!from || from <= day) && (!to || to >= day)
  })
  const sorted = sortRuns(matches.filter(r => inView(r, view)), sort)
  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize))
  const page = Math.max(1, Math.min(pageCount, Number(value('page')) || 1))
  const visible = sorted.slice((page - 1) * pageSize, page * pageSize)
  const activeIndex = visible.findIndex(run => run.id === active)
  const current = visible[activeIndex]
  const selected = sorted.filter(run => checked.has(run.id))
  const exportRows = selected.length ? selected : sorted

  function update(changes: Record<string, string>, replace = false) {
    const next = new URLSearchParams(params)
    for (const [key, text] of Object.entries(changes)) {
      if (text) next.set(key, text)
      else next.delete(key)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next, { replace })
  }

  function activate(id: number) {
    setActive(id)
    document.getElementById('run-row-' + id)?.scrollIntoView?.({ block: 'nearest' })
  }

  function step(direction: 'next' | 'previous') {
    const row = visible[rowIndex(activeIndex, visible.length, direction)]
    if (row) activate(row.id)
  }

  function toggle(id: number) {
    setChecked(previous => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function changeSort(key: RunColumn) {
    update({ sort: key, direction: sort.column !== key || !sort.ascending ? 'asc' : 'desc' })
  }

  function open(run: Run | undefined) {
    if (run) void navigate('/runs/' + run.id)
  }

  useShortcuts({
    search: () => search.current?.focus(), next: () => step('next'), previous: () => step('previous'),
    open: () => open(current), select: () => { if (current) toggle(current.id) },
    peek: () => { if (current) setPeek(current.id) },
    export: () => { if (exportRows.length) downloadRuns(exportRows) },
    escape: () => { setActive(undefined); setChecked(new Set()) },
  })

  const activeFilters = filters.filter(filter => value(filter.key))
  const hasFilters = !!(activeFilters.length || date || from || to || query)
  const selection = { activeId: current?.id, activate, checked, toggle, peek: setPeek }
  return <div className="page-padding flex h-full min-h-0 flex-col gap-3">
    <PageActions><Button variant="outline" type="button" onClick={() => downloadRuns(exportRows)} disabled={!exportRows.length}>
      <Download className="size-3.5" />Export CSV{selected.length > 0 && ' (' + selected.length + ')'}<ShortcutHint id="export" />
    </Button></PageActions>
    <nav className="flex shrink-0 gap-4 overflow-x-auto border-b" aria-label="Run views">
      {runViews.map(([id, label]) => <button key={id} type="button" aria-pressed={view === id} onClick={() => update({ view: id === 'all' ? '' : id })}
        className={cn('flex h-8 shrink-0 items-center gap-1.5 border-b-2 border-transparent text-body text-muted-foreground hover:text-foreground', view === id && 'border-primary font-medium text-primary')}>
        {label}<span className="rounded-sm bg-muted px-1.5 text-meta text-muted-foreground">{matches.filter(run => inView(run, id)).length}</span>
      </button>)}
    </nav>
    <div className="flex shrink-0 flex-wrap items-center gap-2">
      <label className="relative min-w-40 flex-1 sm:max-w-60">
        <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted-foreground" aria-hidden="true" />
        <Input ref={search} className="h-8 bg-card pl-8 pr-8 text-body" placeholder="Search runs…" aria-label="Search runs"
          value={query} onChange={event => update({ q: event.target.value }, true)} />
        <ShortcutHint className="pointer-events-none absolute top-2 right-2" id="search" />
      </label>
      {filters.map(({ key, label, options }) => <select key={key} aria-label={label} value={value(key)}
        className="h-8 max-w-32 rounded-sm border bg-card px-2 text-meta hover:bg-muted"
        onChange={event => update({ [key]: event.target.value })}>
        <option value="">{label}</option>{options.map(([id, text]) => <option key={id} value={id}>{text}</option>)}
      </select>)}
      <details className="relative">
        <summary className="flex h-8 cursor-pointer list-none items-center rounded-sm border bg-card px-2 text-meta hover:bg-muted">Date range</summary>
        <div className="absolute right-0 z-30 grid min-w-44 gap-2 border bg-card p-2 shadow-lg">
          <label className="grid gap-1 text-meta">From<Input type="date" value={from} onChange={event => update({ from: event.target.value, date: '' })} /></label>
          <label className="grid gap-1 text-meta">To<Input type="date" value={to} onChange={event => update({ to: event.target.value, date: '' })} /></label>
        </div>
      </details>
      {hasFilters && <Button type="button" variant="ghost" size="sm" onClick={() => update(Object.fromEntries(['q', 'date', 'from', 'to', ...filters.map(f => f.key)].map(k => [k, ''])))}>Clear</Button>}
    </div>
    {!!(activeFilters.length || date || from || to) && <div className="flex shrink-0 flex-wrap gap-2">
      {activeFilters.map(filter => <FilterChip key={filter.key} text={filter.options.find(([id]) => id === value(filter.key))?.[1] ?? value(filter.key)} onRemove={() => update({ [filter.key]: '' })} />)}
      {date && <FilterChip text={date} onRemove={() => update({ date: '' })} />}
      {(from || to) && <FilterChip text={(from || 'Any start') + ' – ' + (to || 'Any end')} onRemove={() => update({ from: '', to: '' })} />}
    </div>}
    <div className="panel flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        {runs.isPending ? <LoadingState label="Loading runs" /> :
          runs.isError ? <ErrorState title="Could not load runs" error={runs.error} retry={() => void runs.refetch()} /> :
            !sorted.length ? <EmptyState title="No invoice runs found">Try a different search or filter.</EmptyState> :
              <RunsTable runs={visible} sort={sort} onSort={changeSort} selection={selection} now={now} />}
      </div>
      <div className="flex min-h-9 shrink-0 items-center gap-2 border-t px-3 text-meta text-muted-foreground">
        <span>{sorted.length ? 'Showing ' + ((page - 1) * pageSize + 1) + '–' + Math.min(page * pageSize, sorted.length) + ' of ' + sorted.length : 'Showing 0 runs'}</span>
        <div className="ml-auto hidden gap-2 sm:flex">
          <Button size="sm" variant="ghost" disabled={!visible.length} onClick={() => step('previous')}>Previous row <ShortcutHint id="previous" /></Button>
          <Button size="sm" variant="ghost" disabled={!visible.length} onClick={() => step('next')}>Next row <ShortcutHint id="next" /></Button>
          <Button size="sm" variant="ghost" disabled={!current} onClick={() => open(current)}>Open <ShortcutHint id="open" /></Button>
          <Button size="sm" variant="ghost" disabled={!current} onClick={() => current && setPeek(current.id)}>Peek <ShortcutHint id="peek" /></Button>
        </div>
        <div className="ml-auto flex items-center gap-1 sm:ml-0">
          <Button variant="ghost" size="icon-sm" aria-label="Previous page" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}><ChevronLeft /></Button>
          <span>{page} / {pageCount}</span>
          <Button variant="ghost" size="icon-sm" aria-label="Next page" disabled={page >= pageCount} onClick={() => update({ page: String(page + 1) })}><ChevronRight /></Button>
        </div>
      </div>
    </div>
    <PeekDrawer id={peek} onClose={() => setPeek(null)} />
  </div>
}

function FilterChip({ text, onRemove }: { text: string; onRemove: () => void }) {
  return <button type="button" aria-label={'Remove filter ' + text} onClick={onRemove} className="inline-flex items-center gap-1 rounded-sm border bg-card px-1.5 py-0.5 text-meta hover:bg-muted">{text}<X aria-hidden="true" className="size-3" /></button>
}
