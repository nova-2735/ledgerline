import { useState } from 'react'
import { CalendarDays, ChevronDown, CircleCheck, Clock3, FileText, IndianRupee, Inbox as InboxIcon, Search, ShieldCheck, Timer } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Schemas } from '@/api/client'
import { useRuns, useStats } from '@/api/hooks'
import { DecisionsByDay } from '@/components/charts/DecisionsByDay'
import { TopReasons } from '@/components/charts/TopReasons'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { KpiCard } from '@/components/KpiCard'
import { RunsTable } from '@/components/RunsTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { duration, inr, pct } from '@/lib/format'
import { outcomes, routes, runStatuses } from '@/lib/labels'
import { cn } from '@/lib/utils'

const filters = {
  all: 'All outcomes', APPROVE: 'Approved', HOLD: 'On hold', RETURN: 'Returned', REJECT: 'Rejected',
} satisfies Record<Schemas['Outcome'] | 'all', string>
const pageSize = 50

export function Dashboard() {
  const [outcome, setOutcome] = useState<keyof typeof filters>('all')
  const [status, setStatus] = useState<Schemas['RunStatus'] | ''>('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const active = useRuns({ status: 'running', limit: 1 })
  const refreshing = Boolean(active.data?.total)
  const stats = useStats(refreshing)
  const runs = useRuns({ outcome: outcome === 'all' ? null : outcome, status: status || null, q: search.trim(), offset, limit: pageSize }, refreshing)
  const kpis = stats.data?.kpis

  return <div className="space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3 pb-1">
      <div>
        <h1 className="page-title">Dashboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">Track invoice decisions and see where your team needs to step in.</p>
      </div>
      <div className="inline-flex items-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm font-medium text-slate-700">
        <CalendarDays aria-hidden="true" className="size-4 text-slate-500" />Last 30 days
      </div>
    </header>
    {stats.isError && <ErrorState title="Could not load dashboard totals" error={stats.error} retry={() => void stats.refetch()} />}
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      {kpis ? <>
        <KpiCard title="Invoices processed" value={kpis.processed} icon={FileText} />
        <KpiCard title="Value processed" value={inr(kpis.value_processed)} icon={IndianRupee} />
        <KpiCard title="Touchless approvals" value={pct(kpis.touchless_rate)} icon={CircleCheck}
          detail="Invoices approved without a human review step." />
        <KpiCard title="Awaiting review" value={kpis.awaiting_review} icon={InboxIcon} to="/queue" />
        <KpiCard title="Median time to decision" value={duration(kpis.median_decision_ms)} icon={Timer}
          detail="Measured on live runs. Seeded runs are excluded." />
        <KpiCard title="Exposure stopped" value={inr(kpis.exposure_stopped)} icon={ShieldCheck}
          detail="Value held back for duplicates, changed bank details, over-billing and unknown vendors." />
      </> : stats.isPending && Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-25" />)}
    </div>
    {stats.data && <>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <DecisionsByDay data={stats.data.by_day} />
        <TopReasons data={stats.data.by_reason} />
      </div>
      <section className="panel flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold"><Clock3 aria-hidden="true" className="size-4 text-indigo-600" />Waiting on</h2>
        {stats.data.by_route.length ? stats.data.by_route.map(({ route, count }) =>
          <Link to={`/queue?route=${route}`} key={route} className="inline-flex items-center gap-2 rounded-full bg-indigo-50 px-2.5 py-1 text-sm font-medium text-indigo-800 hover:bg-indigo-100">
            {routes[route]} <span className="rounded-full bg-white px-1.5 text-xs tabular-nums">{count}</span>
          </Link>,
        ) : <span className="text-sm text-muted-foreground">No invoices waiting for review</span>}
      </section>
    </>}
    <section className="panel">
      <header className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-3 sm:px-5">
        <h2 className="section-title">Invoice runs</h2>
        {runs.data && <span className="text-sm text-muted-foreground tabular-nums">{runs.data.total} {runs.data.total === 1 ? 'run' : 'runs'}</span>}
      </header>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-3 sm:px-5">
        <div className="flex flex-wrap gap-1" aria-label="Filter by outcome">
          {(Object.keys(filters) as (keyof typeof filters)[]).map(key => <button type="button" key={key}
            aria-pressed={outcome === key} aria-label={key === 'all' ? undefined : outcomes[key]}
            onClick={() => { setOutcome(key); setOffset(0) }}
            className={cn('rounded-md px-2.5 py-1.5 text-sm font-medium', outcome === key ? 'bg-indigo-50 text-indigo-800' : 'text-slate-600 hover:bg-slate-100')}>
            {filters[key]}
          </button>)}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <select aria-label="Run status" className="h-8 appearance-none rounded-lg border border-input bg-white py-1 pr-7 pl-2 text-sm"
              value={status} onChange={event => { setStatus(event.target.value as typeof status); setOffset(0) }}>
              <option value="">All statuses</option>
              {Object.entries(runStatuses).map(([key, label]) => <option value={key} key={key}>{label}</option>)}
            </select>
            <ChevronDown aria-hidden="true" className="pointer-events-none absolute top-2 right-2 size-4 text-slate-500" />
          </div>
          <div className="relative">
            <Search aria-hidden="true" className="pointer-events-none absolute top-2 left-2 size-4 text-slate-500" />
            <Input aria-label="Search invoice runs" placeholder="Search vendor, invoice or PO" className="w-64 pl-8"
              value={search} onChange={event => { setSearch(event.target.value); setOffset(0) }} />
          </div>
        </div>
      </div>
      {runs.isPending && <LoadingState label="Loading invoice runs" />}
      {runs.isError && <div className="p-4"><ErrorState title="Could not load invoice runs" error={runs.error} retry={() => void runs.refetch()} /></div>}
      {runs.data && (runs.data.total > 0 || (outcome !== 'all' || status || search) ?
        <RunsTable runs={runs.data.items} /> :
        <EmptyState title="No invoices processed yet"><Link className="text-indigo-700 underline" to="/inbox">Go to the AP inbox</Link></EmptyState>)}
      {runs.data && (offset > 0 || runs.data.total > pageSize) && <footer className="flex justify-end gap-2 border-t p-3">
        <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(offset - pageSize)}>Previous</Button>
        <Button variant="outline" size="sm" disabled={offset + pageSize >= runs.data.total} onClick={() => setOffset(offset + pageSize)}>Next</Button>
      </footer>}
    </section>
  </div>
}
