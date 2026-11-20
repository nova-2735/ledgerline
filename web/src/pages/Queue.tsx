import { useEffect, useState } from 'react'
import { queryOptions, useQueries, useQueryClient } from '@tanstack/react-query'
import { Clock3, UserRound } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type Schemas } from '@/api/client'
import { queryKeys, useQueue } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { approvalBlock } from '@/components/run/DecisionPanel'
import { ReviewDialogs } from '@/components/run/ReviewDialogs'
import { Button } from '@/components/ui/button'
import { inr } from '@/lib/format'
import { actions, reasons, routes } from '@/lib/labels'
import { cn } from '@/lib/utils'

type Run = Schemas['RunDetail']
type QueueRoute = Exclude<Schemas['Route'], 'none'>
type Action = Schemas['ActionType']
const tabs: QueueRoute[] = ['ap_clerk', 'buyer', 'receiving', 'treasury', 'procurement', 'controller', 'vendor']
const severity = { info: 0, low: 1, medium: 2, high: 3, critical: 4 }

function priority(run?: Run) {
  return Math.max(0, ...(run?.checks ?? []).filter(check => !check.resolved_by_review && ['fail', 'warn'].includes(check.status))
    .map(check => severity[check.severity]))
}

function ageLabel(hours: number) {
  if (hours < 1) return hours < .02 ? 'Just arrived' : `${Math.floor(hours * 60)} min waiting`
  if (hours < 24) return `${Math.floor(hours)} h waiting`
  return `${Math.floor(hours / 24)} d waiting`
}

export function Queue() {
  const [params] = useSearchParams()
  const route = tabs.find(item => item === params.get('route'))
  const query = useQueue(route)
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<{ id: number; action: Action } | null>(null)
  const [reviewing, setReviewing] = useState<number[]>([])
  const ids = [...new Set([...(query.data?.items.map(item => item.id) ?? []), ...reviewing])]
  const details = useQueries({
    queries: ids.map(id => queryOptions({
      queryKey: queryKeys.run(id), queryFn: ({ signal }) => api.getRun(id, signal),
      refetchInterval: query => reviewing.includes(id) && (!query.state.data || isProcessing(query.state.data)) ? 850 : false,
    })),
  })
  const byId = new Map(ids.map((id, index) => [id, details[index]]))

  useEffect(() => {
    const settled = details.flatMap(({ data }) => data && reviewing.includes(data.id) && !isProcessing(data) ? [data.id] : [])
    if (!settled.length) return
    setReviewing(ids => ids.filter(id => !settled.includes(id)))
    for (const key of [queryKeys.queue, queryKeys.stats, queryKeys.runs, queryKeys.orders, ['purchase-order']]) {
      void queryClient.invalidateQueries({ queryKey: key })
    }
  }, [details, queryClient, reviewing])

  const counts = query.data?.counts ?? {}
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0)
  const items = [...(query.data?.items ?? [])].sort((left, right) =>
    priority(byId.get(right.id)?.data) - priority(byId.get(left.id)?.data) || right.age_hours - left.age_hours,
  )
  const selectedRun = selected && byId.get(selected.id)?.data

  function onReviewed(run: Run) {
    queryClient.setQueryData(queryKeys.run(run.id), run)
    setReviewing(ids => [...new Set([...ids, run.id])])
    void queryClient.invalidateQueries({ queryKey: queryKeys.queue })
  }

  return <div className="space-y-4">
    <header>
      <h1 className="page-title">Review queue</h1>
      <p className="mt-1 text-sm text-muted-foreground">See who needs to act and record the next step for each invoice.</p>
    </header>
    <nav aria-label="Review queue by owner" className="panel flex flex-wrap gap-1 px-2 py-2">
      {([undefined, ...tabs] as const).map(owner => {
        const active = owner === route
        return <Link key={owner ?? 'all'} to={owner ? `/queue?route=${owner}` : '/queue'} aria-current={active ? 'page' : undefined}
          className={cn('flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium', active ? 'bg-indigo-50 text-indigo-800' : 'text-slate-700 hover:bg-slate-100')}>
          {owner ? routes[owner] : 'All'}{query.data && <span className={cn('rounded-full px-1.5 text-xs tabular-nums', active ? 'bg-indigo-100' : 'bg-slate-100')}>
            {owner ? counts[owner] ?? 0 : total}
          </span>}
        </Link>
      })}
    </nav>
    {query.isPending && <div className="panel"><LoadingState label="Loading the review queue" /></div>}
    {query.isError && <ErrorState title="Could not load the review queue" error={query.error} retry={() => void query.refetch()} />}
    {query.data && !items.length && <div className="panel"><EmptyState title="Nothing waiting. Nice." /></div>}
    {!!items.length && <ul className="grid items-start gap-3 lg:grid-cols-2 xl:grid-cols-3">
      {items.map(item => {
        const detail = byId.get(item.id)
        const run = detail?.data
        const available = run?.decision?.handoff?.actions ?? []
        const primary = available.find(action => action !== 'approve' || !approvalBlock(run!))
        const inReview = reviewing.includes(item.id)
        return <li key={item.id} className="panel grid gap-3 p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="section-title">{item.vendor_name ?? 'Unknown vendor'}</h2>
              <p className="text-sm text-muted-foreground tabular-nums">{item.invoice_number ?? item.display_id}</p>
            </div>
            <OutcomeBadge outcome={item.final_outcome ?? item.outcome} />
          </div>
          <dl className="flex flex-wrap items-end justify-between gap-2 border-y py-2 text-sm">
            <div><dt className="sr-only">Invoice amount</dt><dd className="font-semibold tabular-nums">{inr(item.total)}</dd></div>
            <div><dt className="sr-only">Time waiting</dt><dd className="flex items-center gap-1 text-xs text-muted-foreground"><Clock3 aria-hidden="true" className="size-3.5" />{ageLabel(item.age_hours)}</dd></div>
          </dl>
          <div className="space-y-1">
            {item.route && <p className="flex items-center gap-1.5 text-xs font-medium text-indigo-800"><UserRound aria-hidden="true" className="size-3.5" />{routes[item.route]}</p>}
            <p className="text-sm font-semibold">{item.question}</p>
            {item.primary_reason && <p className="text-xs text-muted-foreground">{reasons[item.primary_reason]}</p>}
            {item.amount_at_risk && <p className="text-xs text-muted-foreground tabular-nums">{inr(item.amount_at_risk)} at risk</p>}
          </div>
          {detail?.isError && <ErrorState title="Could not load review actions" error={detail.error} retry={() => void detail.refetch()} />}
          <div className="flex flex-wrap gap-2">
            {primary && <Button type="button" size="sm" disabled={inReview} onClick={() => setSelected({ id: item.id, action: primary })}>{actions[primary]}</Button>}
            {inReview && <span className="self-center text-xs text-muted-foreground" role="status">Applying review…</span>}
            <Button asChild size="sm" variant="outline"><Link to={`/runs/${item.id}`}>Open</Link></Button>
          </div>
        </li>
      })}
    </ul>}
    {selectedRun && selected && <ReviewDialogs action={selected.action} run={selectedRun} onClose={() => setSelected(null)} onReviewed={onReviewed} />}
  </div>
}

function isProcessing(run: Run) {
  return run.status === 'running' || run.status === 'queued'
}
