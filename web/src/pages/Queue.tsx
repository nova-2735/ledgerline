import { useEffect, useRef, useState } from 'react'
import { useQueries, useQueryClient } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type Schemas } from '@/api/client'
import { queryKeys, useQueue } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { PeekDrawer } from '@/components/PeekDrawer'
import { StatusSquare } from '@/components/OutcomeBadge'
import { RowKeys } from '@/components/RowKeys'
import { ShortcutHint } from '@/components/ShortcutHint'
import { WorkFolders } from '@/components/WorkFolders'
import { ReviewDialogs } from '@/components/run/ReviewDialogs'
import { actionShortcut, approvalBlock, primaryReviewAction, reviewActions } from '@/components/run/reviewActions'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { age } from '@/lib/dashboard'
import { inr } from '@/lib/format'
import { actions, reasons, routes } from '@/lib/labels'
import { effectiveOutcome } from '@/lib/runList'
import { rowIndex, useShortcuts, type Shortcut } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

type Run = Schemas['RunDetail']
type Action = Schemas['ActionType']
const owners = ['ap_clerk', 'buyer', 'receiving', 'treasury', 'procurement', 'controller', 'vendor'] as const
const ranks = { info: 0, low: 1, medium: 2, high: 3, critical: 4 }

function priority(run?: Run) {
  return Math.max(0, ...(run?.checks ?? []).filter(check => check.status === 'fail' && !check.resolved_by_review).map(check => ranks[check.severity]))
}

function isProcessing(run: Run) {
  return run.status === 'running' || run.status === 'queued'
}

export function Queue() {
  const [params, setParams] = useSearchParams()
  const route = owners.find(value => value === params.get('route'))
  const focus = Number(params.get('focus')) || undefined
  const query = useQueue()
  const cache = useQueryClient()
  const navigate = useNavigate()
  const searchInput = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [activeId, setActiveId] = useState<number | null | undefined>()
  const [peek, setPeek] = useState<number | null>(null)
  const [selected, setSelected] = useState<{ id: number; action: Action } | null>(null)
  const [reviewing, setReviewing] = useState<number[]>([])
  const queue = query.data?.items ?? []
  const ids = [...new Set([...queue.map(run => run.id), ...reviewing])]
  const details = useQueries({
    queries: ids.map(id => ({
      queryKey: queryKeys.run(id),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.getRun(id, signal),
      refetchInterval: ({ state }: { state: { data?: Run } }) => reviewing.includes(id) && (!state.data || isProcessing(state.data)) ? 850 : false,
    })),
  })
  const byId = new Map(ids.map((id, index) => [id, details[index]]))
  const selectedRun = selected ? byId.get(selected.id)?.data : undefined

  useEffect(() => {
    const settled = details.flatMap(({ data }) => data && reviewing.includes(data.id) && !isProcessing(data) ? [data.id] : [])
    if (!settled.length) return
    setReviewing(ids => ids.filter(id => !settled.includes(id)))
    for (const queryKey of [queryKeys.queue, queryKeys.stats, queryKeys.runs, queryKeys.orders, ['purchase-order']]) void cache.invalidateQueries({ queryKey })
  }, [details, cache, reviewing])

  const rows = queue.filter(run => (!route || run.route === route) && [
    run.vendor_name, run.invoice_number, run.display_id, run.question, run.route && routes[run.route],
  ].some(value => value?.toLowerCase().includes(search.trim().toLowerCase())))
    .sort((a, b) => priority(byId.get(b.id)?.data) - priority(byId.get(a.id)?.data) || b.age_hours - a.age_hours)
  const own = (id: string) => id === 'all' ? queue : queue.filter(row => row.route === id)
  const folders = ['all', ...owners].map(id => {
    const items = own(id)
    return {
      id, label: id === 'all' ? 'All owners' : routes[id as typeof owners[number]],
      count: items.length, age: items.length ? age(Math.max(...items.map(run => run.age_hours))) : undefined,
    }
  })
  const current = activeId === null ? undefined : rows.find(row => row.id === (activeId ?? focus)) ?? rows[0]
  const currentDetail = current && byId.get(current.id)?.data
  const focusDetail = focus ? byId.get(focus)?.data : undefined
  const actionParam = params.get('action')
  const focusAction = actionParam === 'primary' ? primaryReviewAction(focusDetail) :
    reviewActions(focusDetail).find(action => action === actionParam && (action !== 'approve' || !approvalBlock(focusDetail!)))
  useEffect(() => {
    if (!focus || !focusDetail || !actionParam) return
    const next = new URLSearchParams(params)
    next.delete('action')
    setParams(next, { replace: true })
    if (focusAction) setSelected({ id: focus, action: focusAction })
  }, [focus, focusDetail, actionParam, focusAction, params, setParams])

  function activate(id: number) {
    setActiveId(id)
    document.getElementById('queue-row-' + id)?.scrollIntoView?.({ block: 'nearest' })
  }

  function step(direction: 'next' | 'previous') {
    const row = rows[rowIndex(rows.findIndex(run => run.id === current?.id), rows.length, direction)]
    if (row) activate(row.id)
  }

  function openAction(id: number, action: Action) {
    const run = byId.get(id)?.data
    if (!run || reviewing.includes(id) || !reviewActions(run).includes(action) || (action === 'approve' && approvalBlock(run))) return
    setSelected({ id, action })
  }

  const actionKeys = Object.fromEntries(reviewActions(currentDetail).flatMap(action => {
    const key = actionShortcut(action)
    return key && current ? [[key, () => openAction(current.id, action)]] : []
  })) as Partial<Record<Shortcut, () => void>>

  useShortcuts({
    ...actionKeys, search: () => searchInput.current?.focus(),
    next: () => step('next'), previous: () => step('previous'),
    open: () => { if (current) void navigate('/runs/' + current.id) },
    peek: () => { if (current) setPeek(current.id) },
    escape: () => setActiveId(null),
  })

  function onReviewed(run: Run) {
    cache.setQueryData(queryKeys.run(run.id), run)
    setReviewing(ids => [...new Set([...ids, run.id])])
    void cache.invalidateQueries({ queryKey: queryKeys.queue })
  }

  return <div className="page-padding h-full min-h-0">
    <div className="grid min-h-full grid-cols-1 gap-px border bg-border lg:h-full lg:min-h-0 lg:grid-cols-[200px_minmax(0,1fr)]">
      <WorkFolders title="Owners" folders={folders} active={route ?? 'all'} select={id => { setActiveId(undefined); setParams(id === 'all' ? {} : { route: id }) }} />
      <section aria-label="Awaiting review" className="flex min-h-0 min-w-0 flex-col bg-card">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b px-2">
          <label className="relative min-w-0 flex-1 sm:max-w-64">
            <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" aria-hidden="true" />
            <Input ref={searchInput} value={search} onChange={event => { setSearch(event.target.value); setActiveId(undefined) }}
              aria-label="Search review queue" placeholder="Search review queue…" className="h-8 pl-8 pr-7 text-body" />
            <ShortcutHint id="search" className="pointer-events-none absolute top-2 right-2" />
          </label>
          <span className="ml-auto hidden text-meta text-muted-foreground sm:inline">{rows.length} waiting</span>
          <RowKeys onStep={step} disabled={!rows.length} />
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {query.isPending ? <LoadingState label="Loading the review queue" /> :
            query.isError ? <ErrorState title="Could not load the review queue" error={query.error} retry={() => void query.refetch()} /> :
            !rows.length ? <EmptyState title="Nothing waiting."><Link className="text-link" to="/runs">View runs</Link></EmptyState> :
            <table aria-label="Invoices awaiting review" className="w-full min-w-[710px] table-fixed">
              <colgroup><col className="w-8" /><col className="w-[160px]" /><col className="w-[114px]" /><col className="w-[52px]" /><col /><col className="w-[146px]" /><col className="w-[77px]" /></colgroup>
              <thead className="table-head"><tr>
                <th scope="col"><span className="sr-only">Severity</span></th>{['Vendor', 'Amount', 'Age', 'Next step', 'Action', 'Run'].map((label, index) =>
                  <th key={label} scope="col" className={cn('px-2 font-medium', (index === 1 || index === 2) && 'text-right')}>{label}</th>)}
              </tr></thead>
              <tbody>
                {rows.map(run => {
                  const detail = byId.get(run.id)
                  const primary = primaryReviewAction(detail?.data)
                  const active = current?.id === run.id
                  const working = reviewing.includes(run.id)
                  const key = primary && actionShortcut(primary)
                  const critical = priority(detail?.data) === ranks.critical
                  return <tr key={run.id} id={'queue-row-' + run.id} onClick={event => { if (!(event.target as Element).closest('button, a')) activate(run.id) }}
                    className={cn('table-row cursor-pointer hover:bg-muted', active && 'bg-accent hover:bg-accent')}>
                    <td className={cn('border-l-2 border-l-transparent pl-2', critical && 'border-l-reject')} title={critical ? 'Critical' : undefined}>
                      <StatusSquare outcome={critical ? 'REJECT' : effectiveOutcome(run)} />
                    </td>
                    <td className="truncate px-2 font-medium" title={run.vendor_name ?? undefined}>{run.vendor_name ?? 'Unknown vendor'}</td>
                    <td className="px-2 text-right">{inr(run.total)}</td>
                    <td className="px-2 text-right text-meta text-muted-foreground">{age(run.age_hours)}</td>
                    <td className="truncate px-2 text-meta" title={run.question}>{run.question || (run.primary_reason && reasons[run.primary_reason]) || 'Review invoice'}</td>
                    <td className="px-2">
                      {working ? <span role="status" className="text-meta text-muted-foreground">Applying review…</span> :
                        primary ? <Button variant="outline" size="sm" className="max-w-full" onClick={() => { setActiveId(run.id); openAction(run.id, primary) }}>
                          <span className="truncate">{actions[primary]}</span>{key && <ShortcutHint id={key} />}
                        </Button> : detail?.isError ? <Button variant="outline" size="sm" onClick={() => void detail.refetch()}>Retry actions</Button> :
                          <Button asChild variant="outline" size="sm"><Link to={'/runs/' + run.id}>Review run</Link></Button>}
                    </td>
                    <td className="identifier px-2"><Link to={'/runs/' + run.id} className="text-link">{run.display_id}</Link></td>
                  </tr>
                })}
              </tbody>
            </table>}
        </div>
        <div className="flex min-h-9 shrink-0 items-center justify-end gap-1 border-t px-2">
          <Button type="button" variant="ghost" size="sm" disabled={!current} onClick={() => current && setPeek(current.id)}>Peek <ShortcutHint id="peek" /></Button>
          <Button type="button" variant="ghost" size="sm" disabled={!current} onClick={() => current && void navigate('/runs/' + current.id)}>Open run <ShortcutHint id="open" /></Button>
        </div>
      </section>
    </div>
    <PeekDrawer id={peek} onClose={() => setPeek(null)} />
    {selectedRun && selected && <ReviewDialogs action={selected.action} run={selectedRun} onClose={() => setSelected(null)} onReviewed={onReviewed} />}
  </div>
}
