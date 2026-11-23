import { Suspense, useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Outlet, useMatch, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api, setAccessCode } from '@/api/client'
import { isAccessError, queryKeys, useHealth, useQueue, useRuns } from '@/api/hooks'
import { ErrorState, LoadingState } from '@/components/EmptyState'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { AppSidebar } from './AppSidebar'
import { CommandPalette } from './CommandPalette'
import { PageActionsTarget, RunConnection } from './PageActions'
import { ShortcutSheet } from './ShortcutSheet'
import { StatusBar, healthLabel } from './StatusBar'
import { TopBar } from './TopBar'
import { destinations, useShortcuts, type Shortcut } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

const accessKey = 'ledgerline-access'

export function restoreAccessCode() {
  try { setAccessCode(sessionStorage.getItem(accessKey)) } catch { /* Storage may be unavailable. */ }
}

function readSetting(key: string) {
  try { return localStorage.getItem(key) } catch { return null }
}

function saveSetting(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* Storage may be unavailable. */ }
}

export function AppShell() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const health = useHealth()
  const [dark, setDark] = useState(() => readSetting('ledgerline-theme') === 'dark')
  const [collapsed, setCollapsed] = useState(() => readSetting('ledgerline-sidebar') === 'rail' || window.innerWidth < 760)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [actionTarget, setActionTarget] = useState<HTMLDivElement | null>(null)
  const runRoute = useMatch('/runs/:id')
  const [runLive, setRunLive] = useState(false)
  const runs = useRuns({ limit: 1 })
  const toggleTheme = () => setDark(value => !value)
  const toggleSidebar = () => setCollapsed(value => !value)
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    saveSetting('ledgerline-theme', dark ? 'dark' : 'light')
  }, [dark])
  useEffect(() => saveSetting('ledgerline-sidebar', collapsed ? 'rail' : 'expanded'), [collapsed])

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

  const go = Object.fromEntries(destinations.map(({ id, path }) => [id, () => void navigate(path)])) as Partial<Record<Shortcut, () => void>>
  useShortcuts({
    ...go,
    palette: () => setPaletteOpen(true),
    help: () => setShortcutsOpen(true),
    theme: toggleTheme,
    ...(runRoute ? {} : { sidebar: toggleSidebar }),
  }, !gate && dialog === null)
  const openReset = () => { reset.reset(); setDialog('reset') }

  function submitCode(event: FormEvent) {
    event.preventDefault()
    if (code.trim()) unlock.mutate(code.trim())
  }

  return <div className={cn('grid h-dvh overflow-hidden grid-rows-[minmax(0,1fr)_28px]', collapsed ? 'grid-cols-[52px_minmax(0,1fr)]' : 'grid-cols-[220px_minmax(0,1fr)]')}>
    <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:bg-card focus:p-2">Skip to content</a>
    <AppSidebar collapsed={collapsed} count={count} showSidebarShortcut={!runRoute} toggle={toggleSidebar} openPalette={() => setPaletteOpen(true)} />
    <div className="flex min-h-0 min-w-0 flex-col">
      <TopBar actionsRef={setActionTarget} />
      <main id="main" className="min-h-0 flex-1 overflow-auto">
        <RunConnection.Provider value={setRunLive}><PageActionsTarget.Provider value={actionTarget}><Suspense fallback={<LoadingState label="Loading page" />}><Outlet /></Suspense></PageActionsTarget.Provider></RunConnection.Provider>
      </main>
    </div>
    <StatusBar health={health.data?.health} ms={health.data?.ms} error={health.isError} count={runs.data?.total}
      dark={dark} live={runLive} onHealth={() => setDialog('health')}
      onTheme={toggleTheme} onHelp={() => setShortcutsOpen(true)} />
    <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} onReset={openReset} onSidebar={toggleSidebar} />
    <ShortcutSheet open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    <Dialog open={gate} onOpenChange={() => undefined}>
      <DialogContent showCloseButton={false} onEscapeKeyDown={event => event.preventDefault()} onInteractOutside={event => event.preventDefault()}>
        <DialogHeader><DialogTitle>Enter demo access code</DialogTitle><DialogDescription>Use the access code for this Ledgerline workspace.</DialogDescription></DialogHeader>
        <form onSubmit={submitCode} className="space-y-3">
          <Input aria-label="Access code" type="password" value={code} onChange={event => setCode(event.target.value)} required />
          {unlock.isError && <ErrorState title={isAccessError(unlock.error) ? 'That access code did not work' : 'Could not check the access code'} retry={() => unlock.mutate(code)} />}
          <DialogFooter><Button type="submit" disabled={!code.trim() || unlock.isPending}>Continue</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    <Dialog open={dialog !== null} onOpenChange={open => { if (!open && !reset.isPending) setDialog(null) }}>
      <DialogContent>
        {dialog === 'reset' ? <>
          <DialogHeader><DialogTitle>Reset demo data?</DialogTitle><DialogDescription>This deletes runs and reviews added in the demo and restores the seeded data.</DialogDescription></DialogHeader>
          {reset.isError && <ErrorState title="Could not reset demo data" error={reset.error} retry={() => reset.mutate()} />}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={reset.isPending} onClick={() => setDialog(null)}>Cancel</Button>
            <Button type="button" variant="destructive" disabled={reset.isPending} onClick={() => reset.mutate()}>{reset.isPending ? 'Resetting…' : 'Reset demo data'}</Button>
          </DialogFooter>
        </> : <>
          <DialogHeader><DialogTitle>API health</DialogTitle><DialogDescription>Connection and invoice reader status.</DialogDescription></DialogHeader>
          {health.data && <dl className="grid grid-cols-[auto_1fr] gap-3 text-sm">
            <dt className="text-muted-foreground">Connection</dt><dd>{health.data.health.status === 'ok' ? 'Available' : health.data.health.status}</dd>
            <dt className="text-muted-foreground">Invoice reader</dt><dd>{healthLabel(health.data.health)}</dd>
            <dt className="text-muted-foreground">Database</dt><dd>{health.data.health.db === 'ok' ? 'Available' : health.data.health.db}</dd>
          </dl>}
          {health.isError && <ErrorState title="API health is unavailable" error={health.error} retry={() => void health.refetch()} />}
          {health.isPending && <p role="status" className="text-sm text-muted-foreground">Checking connection…</p>}
        </>}
      </DialogContent>
    </Dialog>
  </div>
}
