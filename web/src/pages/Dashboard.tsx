import { lazy, Suspense, useState } from 'react'
import { useQueries, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, RefreshCw } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Schemas } from '@/api/client'
import { queryKeys, useAllRuns, useHealth, useQueue, useStats } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { KpiTile } from '@/components/KpiTile'
import { PageActions } from '@/components/layout/PageActions'
import { StatusSquare } from '@/components/OutcomeBadge'
import { Panel } from '@/components/Panel'
import { ShortcutHint } from '@/components/ShortcutHint'
import { RunsTable } from '@/components/RunsTable'
import { Button } from '@/components/ui/button'
import { ReviewDialogs } from '@/components/run/ReviewDialogs'
import { actionLabel, actionShortcut, primaryReviewAction, reviewActions } from '@/components/run/reviewActions'
import { age, dayBefore, greatestRisk, periodDelta, riskLabels, subtractPeriods, type Metric } from '@/lib/dashboard'
import { duration, inr, istDate, pct } from '@/lib/format'
import { reasons, routes } from '@/lib/labels'
import { businessNow, dayOf, effectiveOutcome } from '@/lib/runList'
import { shortcuts, useShortcuts, type Shortcut } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

const Decisions = lazy(() => import('@/components/DecisionsChart'))

type Day = Schemas['StatsDay']
const periods = [['7D', 7, 'week'], ['30D', 30, 'month'], ['90D', 90, 'quarter'], ['All', 365, 'all']] as const
const metrics: [Metric, string, string][] = [
  ['processed', 'Processed', 'Runs that reached an invoice decision during this period.'],
  ['value_processed', 'Value processed', 'Invoice value across all decisions in this period.'],
  ['touchless_rate', 'Touchless approvals', 'Share of runs approved automatically and without review.'],
  ['awaiting_review', 'Awaiting review', 'Current open review cases received during this period.'],
  ['median_decision_ms', 'Median time to decision', 'Median time for live runs. Seeded runs are excluded.'],
  ['exposure_stopped', 'Exposure stopped', 'Largest qualifying risk per run that has yet to be approved.'],
]
const count = new Intl.NumberFormat('en-IN').format
const compactMoney = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', notation: 'compact', maximumFractionDigits: 1 }).format
const money = (value: number) => inr(value.toFixed(2))
const emptyDay = (date: string) => ({ date, APPROVE: 0, HOLD: 0, RETURN: 0, REJECT: 0 })

function metricText(metric: Metric, value: number | null) {
  if (value === null) return '—'
  if (metric === 'value_processed' || metric === 'exposure_stopped') return money(value)
  if (metric === 'touchless_rate') return pct(value)
  if (metric === 'median_decision_ms') return duration(value)
  return count(value)
}

export function Dashboard() {
  const [periodIndex, setPeriod] = useState(2)
  const [period, days] = periods[periodIndex]
  const navigate = useNavigate()
  const cache = useQueryClient()
  const health = useHealth()
  const stats = useStats(true, days)
  const allRuns = useAllRuns(true)
  const queue = useQueue()
  const [refreshing, setRefreshing] = useState(false)
  const samples = Array.from({ length: 5 }, (_, i) => Math.floor(days * (i + 1) / 6))
  const windows = useQueries({
    queries: [...samples, Math.min(days * 2, 365)].map(window => ({
      queryKey: [...queryKeys.stats, window],
      queryFn: ({ signal }: { signal: AbortSignal }) => api.stats({ days: window }, signal),
      staleTime: 60_000,
    })),
  })
  const statsDays = stats.data?.by_day ?? []
  const today = health.data?.health.today ?? statsDays.at(-1)?.date ?? dayOf(new Date().toISOString())
  const apiStart = dayBefore(today, days - 1)
  const all = allRuns.data ?? []
  const first = period === 'All' ? all.reduce((oldest, run) => {
    const day = dayOf(run.created_at)
    return day < oldest ? day : oldest
  }, apiStart) : apiStart
  const rows = all.filter(run => {
    const day = dayOf(run.created_at)
    return day >= first && day <= today
  })
  const attention = (queue.data?.items ?? []).filter(run => dayOf(run.created_at) >= first && dayOf(run.created_at) <= today)
  const history = period === 'All' ? rows.filter(run => run.outcome && dayOf(run.created_at) < apiStart) : []
  const detailIds = [...new Set([...history, ...rows.filter(run => run.outcome && run.final_outcome !== 'APPROVE')].map(run => run.id))]
  const details = useQueries({
    queries: detailIds.map(id => ({ queryKey: queryKeys.run(id), queryFn: ({ signal }: { signal: AbortSignal }) => api.getRun(id, signal), staleTime: 60_000 })),
  })
  const runsById = new Map(details.flatMap(({ data }) => data ? [[data.id, data] as const] : []))
  const exposure = new Map<string, number>()
  const byReason = new Map<string, number>()
  for (const detail of runsById.values()) {
    if (detail.final_outcome === 'APPROVE') continue
    const { amount, type } = greatestRisk(detail)
    if (type) exposure.set(type, (exposure.get(type) ?? 0) + amount)
    if (detail.primary_reason) byReason.set(detail.primary_reason, (byReason.get(detail.primary_reason) ?? 0) + amount)
  }
  const owners = Object.entries(attention.reduce<Record<string, { count: number; oldest: number }>>((map, run) => {
    const owner = run.route ?? 'none'
    const previous = map[owner] ?? { count: 0, oldest: 0 }
    map[owner] = { count: previous.count + 1, oldest: Math.max(previous.oldest, run.age_hours) }
    return map
  }, {})).sort(([, a], [, b]) => b.count - a.count)
  const recent = rows.slice(0, 8)
  const previous = windows.at(-1)?.data?.kpis
  const olderDays = new Map<string, Day>()
  const exceptionRows = new Map((stats.data?.by_reason ?? []).map(reason => [reason.code, { ...reason }]))
  let earlierApprovals = 0
  let earlierExposure = 0
  for (const run of history) {
    const date = dayOf(run.created_at)
    const day = olderDays.get(date) ?? emptyDay(date)
    day[effectiveOutcome(run)!]++
    olderDays.set(date, day)
    const detail = runsById.get(run.id)
    const original = detail?.decision_history[0]
    if (original?.outcome === 'APPROVE' && !detail?.review_actions.length) earlierApprovals++
    if (detail && detail.final_outcome !== 'APPROVE') earlierExposure += greatestRisk(detail).amount
    if (original?.outcome !== 'APPROVE' && original?.primary_reason) {
      const row = exceptionRows.get(original.primary_reason) ?? { code: original.primary_reason, count: 0, amount: '0.00' }
      exceptionRows.set(row.code, { ...row, count: row.count + 1 })
    }
  }
  const dashboardDayMap = new Map(statsDays.map(day => [day.date, day]))
  const byDay = [...[...olderDays.values()].sort((a, b) => a.date.localeCompare(b.date)),
    ...Array.from({ length: days }, (_, index) => dayBefore(today, days - 1 - index)).map(day => dashboardDayMap.get(day) ?? emptyDay(day))]
  const earlierValue = history.reduce((total, run) => total + Number(run.total ?? 0), 0)
  const latestKpis = stats.data?.kpis
  const kpis = latestKpis && history.length ? {
    ...latestKpis,
    processed: latestKpis.processed + history.length,
    value_processed: (Number(latestKpis.value_processed) + earlierValue).toFixed(2),
    touchless_rate: (Math.round(latestKpis.processed * latestKpis.touchless_rate) + earlierApprovals) / (latestKpis.processed + history.length),
    exposure_stopped: (Number(latestKpis.exposure_stopped) + earlierExposure).toFixed(2),
    median_decision_ms: median(rows.filter(run => run.source !== 'seed' && run.outcome).flatMap(run => run.duration_ms ?? [])),
  } : latestKpis
  const [review, setReview] = useState<number>()

  const [dialog, setDialog] = useState<{ run: Schemas['RunDetail']; action: Schemas['ActionType'] } | null>(null)
  function openReview(id: number, action?: Schemas['ActionType']) {
    const run = runsById.get(id)
    const offered = action ?? primaryReviewAction(run)
    if (run && offered) setDialog({ run, action: offered })
    else void navigate('/runs/' + id)
  }
  const dayAmounts = new Map<string, number>()
  for (const run of rows) {
    if (!run.outcome || !run.total) continue
    const day = dayOf(run.created_at)
    dayAmounts.set(day, (dayAmounts.get(day) ?? 0) + Number(run.total.replace('.', '')))
  }

  const dashboardReviewKeys = Object.fromEntries(reviewActions(review == null ? undefined : runsById.get(review)).flatMap(action => {
    const key = actionShortcut(action)
    return key ? [[key, () => review != null && openReview(review, action)]] : []
  })) as Partial<Record<Shortcut, () => void>>
  useShortcuts({
    ...dashboardReviewKeys,
    week: () => setPeriod(0), month: () => setPeriod(1), quarter: () => setPeriod(2), all: () => setPeriod(3),
    queueLink: () => void navigate('/queue'),
    open: () => { if (review != null) openReview(review) },
    escape: () => setReview(undefined),
  })

  function spark(metric: Metric) {
    if (!latestKpis) return []
    const bins = [...samples, days]
    if (metric === 'awaiting_review' || metric === 'median_decision_ms') {
      const series = bins.map((end, i) => {
        const start = bins[i - 1] ?? 0
        const rangeStart = dayBefore(today, end - 1), rangeEnd = dayBefore(today, start)
        const includes = (at: string) => dayOf(at) >= rangeStart && dayOf(at) <= rangeEnd
        if (metric === 'awaiting_review') return attention.filter(run => includes(run.created_at)).length
        const timings = rows.flatMap(run => run.source !== 'seed' && run.duration_ms != null && includes(run.created_at) ? [run.duration_ms] : [])
        return median(timings) ?? 0
      }).reverse()
      if (!history.length) return series
      const earlier = metric === 'awaiting_review' ? attention.filter(run => dayOf(run.created_at) < apiStart).length :
        median(history.filter(run => run.source !== 'seed').flatMap(run => run.duration_ms ?? [])) ?? 0
      return [earlier, ...series]
    }
    const values = [...windows.slice(0, 5).map(query => query.data?.kpis), latestKpis]
    if (values.some(value => !value)) return []
    const series = values.map((value, index) => index === 0 ? Number(value![metric]) : subtractPeriods(value!, values[index - 1]!, metric) ?? 0).reverse()
    if (!history.length) return series
    const earlier = { processed: history.length, value_processed: earlierValue, touchless_rate: earlierApprovals / history.length, exposure_stopped: earlierExposure }
    return [earlier[metric], ...series]
  }

  async function refresh() {
    setRefreshing(true)
    try {
      await Promise.all([queryKeys.stats, queryKeys.runs, queryKeys.queue, queryKeys.health].map(queryKey => cache.invalidateQueries({ queryKey })))
    } finally { setRefreshing(false) }
  }

  return <div className="page-padding">
    <PageActions>
      <div className="flex h-8 shrink-0 items-center divide-x border bg-card" aria-label="Dashboard period">
        {periods.map(([name, , key], index) => <button key={name} type="button" aria-pressed={index === periodIndex}
          title={shortcuts[key].label}
          onClick={() => setPeriod(index)} className={cn('flex h-full items-center gap-1 px-2 text-meta font-medium hover:bg-muted', index === periodIndex && 'bg-accent text-primary hover:bg-accent')}>
          {name}<ShortcutHint id={key} className="hidden md:inline-flex" />
        </button>)}
      </div>
      <Button className="hidden sm:inline-flex" variant="outline" size="icon" aria-label="Refresh dashboard" title="Refresh dashboard" disabled={refreshing} onClick={() => void refresh()}><RefreshCw /></Button>
    </PageActions>
    {stats.isError && <div className="mb-3"><ErrorState title="Could not load dashboard statistics" error={stats.error} retry={() => void stats.refetch()} /></div>}
    <div className="grid grid-cols-12 gap-px border bg-border">
      {metrics.map(([metric, label, info]) => {
        const raw = metric === 'awaiting_review' ? attention.length : kpis?.[metric]
        const current = raw == null ? null : Number(raw)
        const change = kpis && previous && days < 365 ? periodDelta(previous, kpis, metric, current) : null
        const difference = typeof change === 'number' ? change : null
        const tone = metric === 'touchless_rate' && difference ? difference > 0 ? 'good' : 'bad' : undefined
        return <div className="relative col-span-6 grid sm:col-span-4 xl:col-span-2" key={metric}><KpiTile label={label} info={info} value={metricText(metric, current)}
          period={period} delta={change === 'no-prior' ? 'no-prior' : difference == null ? undefined : {
            value: difference,
            text: metric === 'touchless_rate' ? (Math.abs(difference) * 100).toFixed(1) + ' pp' : (metric === 'value_processed' || metric === 'exposure_stopped') ? compactMoney(Math.abs(difference)) : metricText(metric, Math.abs(difference)), tone,
          }} series={spark(metric)} /><Link aria-label={'View runs for ' + label} className="absolute inset-0 hover:outline-1 hover:-outline-offset-1 hover:outline-primary" to={'/runs?view=' + (metric === 'awaiting_review' ? 'review' : metric === 'exposure_stopped' ? 'exceptions' : metric === 'touchless_rate' ? 'approved' : 'all')} /></div>
      })}
      <Panel className="col-span-full lg:col-span-8" title="Decisions per day" action={<span className="text-meta font-normal text-muted-foreground">{istDate(first)} – {istDate(today)}</span>}>
        {stats.isPending ? <LoadingState label="Loading daily decisions" /> : <Suspense fallback={<LoadingState label="Loading daily decisions" />}><Decisions bars={byDay} amounts={dayAmounts} today={today} /></Suspense>}
      </Panel>
      <Panel className="col-span-full lg:col-span-4" title="Exceptions by reason">
        {stats.isPending ? <LoadingState label="Loading exceptions" /> : <Exceptions rows={[...exceptionRows.values()]} amounts={byReason} />}
      </Panel>
      <Panel className="col-span-full flex flex-col lg:col-span-8" title="Needs attention" action={<span className="text-meta font-normal text-muted-foreground">{attention.length} waiting</span>}>
        {queue.isError ? <ErrorState title="Could not load the review queue" error={queue.error} retry={() => void queue.refetch()} /> :
          queue.isPending ? <LoadingState label="Loading review queue" /> :
          !attention.length ? <EmptyState title="Nothing is waiting in this period" /> :
          <div className="overflow-x-auto">
            <table aria-label="Invoices that need attention" className="w-full min-w-[610px] table-fixed">
              <colgroup><col className="w-[92px]" /><col className="w-[126px]" /><col className="w-24" /><col className="w-12" /><col /><col className="w-36" /></colgroup>
              <thead className="table-head"><tr>{['Owner', 'Vendor', 'Amount', 'Age', 'Next step', 'Action'].map((label, index) => <th className={cn('px-2 font-medium', (index === 2 || index === 3) && 'text-right')} key={label} scope="col">{label}</th>)}</tr></thead>
              <tbody>{[...attention].sort((a, b) => (runsById.get(b.id)?.checks.some(c => c.status === 'fail' && c.severity === 'critical') ? 1 : 0) -
                (runsById.get(a.id)?.checks.some(c => c.status === 'fail' && c.severity === 'critical') ? 1 : 0) || b.age_hours - a.age_hours).slice(0, 6).map(run => {
                const detail = runsById.get(run.id)
                const action = primaryReviewAction(detail)
                const actionKey = (action && actionShortcut(action)) || 'open'
                return <tr key={run.id} className={cn('table-row hover:bg-muted', review === run.id && 'bg-accent hover:bg-accent')} onFocus={() => setReview(run.id)}>
                  <td className="px-2"><div className="flex items-center gap-1.5"><StatusSquare outcome={effectiveOutcome(run)} /><span className="truncate" title={run.route ? routes[run.route] : undefined}>{run.route ? routes[run.route] : '—'}</span></div></td>
                  <td className="truncate px-2" title={run.vendor_name ?? undefined}><Link className="text-link" to={'/runs/' + run.id}>{run.vendor_name ?? 'Unknown vendor'}</Link></td>
                  <td className="px-2 text-right text-meta">{inr(run.total)}</td>
                  <td className="px-2 text-right text-meta whitespace-nowrap text-muted-foreground">{age(run.age_hours)}</td>
                  <td className="px-2 py-1 text-meta text-muted-foreground"><span className="line-clamp-2" title={run.question}>{run.question}</span></td>
                  <td className="px-2 text-right"><Button variant="outline" size="sm" className="max-w-full" onClick={() => openReview(run.id, action)}>
                    <span className="truncate" title={action ? actionLabel(action) : 'Review'}>{action ? actionLabel(action) : 'Review'}</span><ShortcutHint id={actionKey} />
                  </Button></td>
                </tr>
              })}</tbody>
            </table>
          </div>}
        <div className="mt-auto flex h-8 items-center justify-end border-t px-3"><Link to="/queue" className="text-link inline-flex items-center gap-1.5 text-meta">Open queue <ShortcutHint id="queueLink" /></Link></div>
      </Panel>
      <Panel className="col-span-full lg:col-span-4" title="Waiting on / Exposure">
        <div className="grid grid-cols-[1fr_auto_auto] items-center gap-x-3 px-3 py-2 text-meta">
          <span className="text-muted-foreground">Owner</span><span className="text-right text-muted-foreground">Open</span><span className="text-right text-muted-foreground">Oldest</span>
          {owners.length ? owners.map(([owner, item]) => <div className="contents" key={owner}>
            <Link to={'/queue?route=' + owner} className="text-link py-1">{routes[owner as Schemas['Route']]}</Link><span className="text-right">{item.count}</span><span className="text-right">{age(item.oldest)}</span>
          </div>) : <span className="col-span-full py-2 text-muted-foreground">No reviews waiting</span>}
        </div>
        <h3 className="border-y bg-muted px-3 py-1.5 text-section">Exposure stopped by type</h3>
        <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 px-3 py-2 text-meta">
          {riskLabels.map(label => <div className="contents" key={label}><dt className="text-muted-foreground">{label}</dt><dd className="text-right">{money(exposure.get(label) ?? 0)}</dd></div>)}
        </dl>
      </Panel>
      <Panel className="col-span-full" title="Recent runs" action={<Link className="text-link inline-flex items-center gap-1.5 text-meta" to="/runs">View all runs <ShortcutHint id="runs" /><ArrowUpRight className="size-3" /></Link>}>
        {allRuns.isPending ? <LoadingState label="Loading recent runs" /> :
          allRuns.isError ? <ErrorState title="Could not load invoice runs" error={allRuns.error} retry={() => void allRuns.refetch()} /> :
          <div className="overflow-auto"><RunsTable runs={recent} now={businessNow(today)} /></div>}
      </Panel>
    </div>
    {dialog && <ReviewDialogs {...dialog} onClose={() => setDialog(null)} onReviewed={run => { cache.setQueryData(queryKeys.run(run.id), run); void navigate('/runs/' + run.id) }} />}
  </div>
}

function median(timings: number[]) {
  timings.sort((a, b) => a - b)
  return timings.length ? (timings[Math.floor((timings.length - 1) / 2)] + timings[Math.floor(timings.length / 2)]) / 2 : null
}

function Exceptions({ rows, amounts }: { rows: Schemas['StatsReason'][]; amounts: Map<string, number> }) {
  const navigate = useNavigate()
  const risk = (code: string) => amounts.get(code) ?? 0
  const sorted = [...rows].sort((a, b) => risk(b.code) - risk(a.code) || b.count - a.count).slice(0, 5)
  const maxRisk = Math.max(0, ...sorted.map(row => risk(row.code)))
  const maxCount = Math.max(1, ...sorted.map(row => row.count))
  if (!sorted.length) return <EmptyState title="No exceptions in this period" />
  return <table aria-label="Exceptions by reason" className="w-full table-fixed">
    <colgroup><col /><col className="w-[42px]" /><col className="w-[92px]" /><col className="w-[50px]" /></colgroup>
    <thead className="table-head"><tr><th className="px-2 font-medium">Reason</th><th className="px-1 text-right font-medium">Count</th><th className="px-2 text-right font-medium">At risk</th><th><span className="sr-only">Relative amount at risk, or frequency when no amount is known</span></th></tr></thead>
    <tbody>{sorted.map(row => <tr key={row.code} onClick={() => void navigate('/runs?reason=' + row.code)} className="table-row cursor-pointer hover:bg-muted">
      <td className="truncate px-2 text-meta"><Link className="text-link" to={'/runs?reason=' + row.code} title={reasons[row.code]}>{reasons[row.code]}</Link></td>
      <td className="px-1 text-right text-meta">{row.count}</td>
      <td className="px-2 text-right text-meta">{risk(row.code) ? money(risk(row.code)) : '—'}</td>
      <td className="pr-2"><div className="h-1 bg-muted"><div className="h-full bg-faint" style={{ width: ((risk(row.code) ? risk(row.code) / maxRisk : row.count / maxCount) * 100) + '%' }} /></div></td>
    </tr>)}</tbody>
  </table>
}
