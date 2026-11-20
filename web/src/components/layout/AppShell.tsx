import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, CircleAlert, ClipboardList, FileStack, LayoutDashboard, ListChecks, Mail, MoreHorizontal, RotateCcw, SlidersHorizontal, Users } from 'lucide-react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api, setAccessCode, type Schemas } from '@/api/client'
import { isAccessError, queryKeys, useHealth, useQueue } from '@/api/hooks'
import { ErrorState } from '@/components/EmptyState'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

const accessKey = 'ledgerline-access'
const navigation = [
  ['/', 'Dashboard', LayoutDashboard], ['/inbox', 'Inbox', Mail], ['/queue', 'Review queue', ListChecks],
  ['/purchase-orders', 'Purchase orders', ClipboardList], ['/vendors', 'Vendors', Users], ['/policy', 'Policy', SlidersHorizontal],
] as const

export function restoreAccessCode() {
  try { setAccessCode(sessionStorage.getItem(accessKey)) } catch { /* Storage may be unavailable. */ }
}

function healthLabel(health: Schemas['HealthResponse']) {
  if (health.llm_provider === 'fake') return 'Offline reader (test data)'
  const provider = health.llm_provider === 'gemini' ? 'Gemini' : health.llm_provider
  return `${provider} · ${health.llm_model} · OCR ${health.ocr_available ? 'on' : 'off'}`
}

export function AppShell() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const health = useHealth()
  const [gate, setGate] = useState(false)
  const [code, setCode] = useState('')
  const [dialog, setDialog] = useState<'health' | 'reset' | null>(null)
  const queue = useQueue(undefined, !gate)
  const count = Object.values(queue.data?.counts ?? {}).reduce((sum, value) => sum + value, 0)

  useEffect(() => {
    const cache = queryClient.getQueryCache()
    if (!gate && cache.getAll().some(query => isAccessError(query.state.error))) setGate(true)
    return cache.subscribe(event => {
      if (!gate && event.type === 'updated' && isAccessError(event.query.state.error)) setGate(true)
    })
  }, [gate, queryClient])

  const unlock = useMutation({
    mutationFn: async (value: string) => {
      setAccessCode(value)
      try { await api.queue() } catch (error) {
        if (isAccessError(error)) setAccessCode(null)
        throw error
      }
    },
    onSuccess: () => {
      try { sessionStorage.setItem(accessKey, code.trim()) } catch { /* Storage may be unavailable. */ }
      void queryClient.resetQueries({ predicate: query => isAccessError(query.state.error) })
      setGate(false)
      setCode('')
      void queryClient.invalidateQueries()
    },
  })

  const reset = useMutation({
    mutationFn: api.resetDemo,
    onSuccess: () => {
      setDialog(null)
      void navigate('/')
      queryClient.removeQueries({ queryKey: ['run'] })
      void queryClient.invalidateQueries({ predicate: query => query.queryKey[0] !== queryKeys.health[0] })
      toast.success('Demo data reset')
    },
  })

  function submitCode(event: FormEvent) {
    event.preventDefault()
    if (code.trim()) unlock.mutate(code.trim())
  }

  return <div className="min-h-screen">
    <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded focus:bg-white focus:p-2">Skip to content</a>
    <header className="border-b bg-white">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-5 px-4 pt-2 sm:px-6 xl:flex-nowrap xl:pt-0">
        <Link to="/" className="order-1 flex shrink-0 items-center gap-2.5 py-2">
          <span className="grid size-9 place-items-center rounded-lg bg-indigo-600 text-white"><FileStack aria-hidden="true" className="size-[19px]" /></span>
          <span><span className="block text-base leading-5 font-semibold tracking-tight">Ledgerline</span>
            <span className="block text-[11px] leading-4 font-medium text-muted-foreground">Invoice → decision</span></span>
        </Link>
        <nav aria-label="Main navigation" className="order-3 flex w-full min-w-0 shrink-0 items-stretch gap-1 overflow-x-auto xl:order-2 xl:w-auto xl:shrink xl:flex-1">
          {navigation.map(([to, label, Icon]) => <NavLink to={to} key={to}
            className={({ isActive }) => cn('flex min-h-12 shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-2 text-sm font-medium xl:min-h-16',
              isActive ? 'border-indigo-600 text-indigo-800' : 'border-transparent text-slate-600 hover:text-slate-950')}>
            <Icon aria-hidden="true" className="size-4" />{label}
            {to === '/queue' && count > 0 && <span className="rounded-full bg-indigo-100 px-1.5 py-0.5 text-xs leading-none text-indigo-800 tabular-nums">{count}</span>}
          </NavLink>)}
        </nav>
        <div className="order-2 ml-auto flex shrink-0 items-center gap-2 xl:order-3">
          <button type="button" onClick={() => setDialog('health')} className={cn('status-chip border py-1 text-xs',
            health.isError ? 'border-rose-200 bg-rose-50 text-rose-800' :
              health.data?.llm_provider === 'fake' ? 'border-amber-200 bg-amber-50 text-amber-900' : 'bg-slate-50 text-slate-700')}>
            {health.isError ? <CircleAlert aria-hidden="true" /> : <Activity aria-hidden="true" />}
            <span className="hidden sm:inline">{health.data ? healthLabel(health.data) : health.isError ? 'API unavailable' : 'Checking API'}</span>
            <span className="sr-only sm:hidden">API health</span>
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Workspace menu"><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => { reset.reset(); setDialog('reset') }}><RotateCcw />Reset demo data</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setDialog('health')}><Activity />API health</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
    <main id="main" className="mx-auto max-w-[1400px] px-4 py-5 sm:px-6 sm:py-6"><Outlet /></main>
    <Dialog open={gate} onOpenChange={() => undefined}>
      <DialogContent showCloseButton={false} onEscapeKeyDown={event => event.preventDefault()} onInteractOutside={event => event.preventDefault()}>
        <DialogHeader><DialogTitle>Enter demo access code</DialogTitle><DialogDescription>Use the access code for this Ledgerline workspace.</DialogDescription></DialogHeader>
        <form onSubmit={submitCode} className="space-y-3">
          <Input aria-label="Access code" type="password" value={code} onChange={event => setCode(event.target.value)} required />
          {unlock.isError && <ErrorState title={isAccessError(unlock.error) ? 'That access code did not work' : 'Could not check the access code'} />}
          <DialogFooter><Button type="submit" disabled={!code.trim() || unlock.isPending}>Continue</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    <Dialog open={dialog !== null} onOpenChange={open => { if (!open && !reset.isPending) setDialog(null) }}>
      <DialogContent>
        {dialog === 'reset' ? <>
          <DialogHeader><DialogTitle>Reset demo data?</DialogTitle><DialogDescription>This deletes runs and reviews added in the demo and restores the seeded data.</DialogDescription></DialogHeader>
          {reset.isError && <ErrorState title="Could not reset demo data" error={reset.error} />}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={reset.isPending} onClick={() => setDialog(null)}>Cancel</Button>
            <Button type="button" variant="destructive" disabled={reset.isPending} onClick={() => reset.mutate()}>{reset.isPending ? 'Resetting…' : 'Reset demo data'}</Button>
          </DialogFooter>
        </> : <>
          <DialogHeader><DialogTitle>API health</DialogTitle><DialogDescription>Connection and invoice reader status.</DialogDescription></DialogHeader>
          {health.data && <dl className="grid grid-cols-[auto_1fr] gap-3 text-sm">
            <dt className="text-muted-foreground">Connection</dt><dd>{health.data.status === 'ok' ? 'Available' : health.data.status}</dd>
            <dt className="text-muted-foreground">Invoice reader</dt><dd>{healthLabel(health.data)}</dd>
            <dt className="text-muted-foreground">Database</dt><dd>{health.data.db === 'ok' ? 'Available' : health.data.db}</dd>
          </dl>}
          {health.isError && <ErrorState title="API health is unavailable" error={health.error} retry={() => void health.refetch()} />}
          {health.isPending && <p role="status" className="text-sm text-muted-foreground">Checking connection…</p>}
        </>}
      </DialogContent>
    </Dialog>
  </div>
}
