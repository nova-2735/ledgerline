import { useContext, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PanelBottom } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, runDocumentUrl, USE_MOCKS, type Schemas } from '@/api/client'
import { queryKeys, useAllRuns, useHealth, useRun } from '@/api/hooks'
import { useRunProgress } from '@/api/useRunProgress'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { PageActions, RunConnection } from '@/components/layout/PageActions'
import { AuditPanel } from '@/components/run/AuditPanel'
import { DecisionPanel } from '@/components/run/DecisionPanel'
import { DocumentViewer } from '@/components/run/DocumentViewer'
import { FieldsPanel } from '@/components/run/FieldsPanel'
import { MatchingPanel } from '@/components/run/MatchingPanel'
import { RecordBar } from '@/components/run/RecordBar'
import { ReviewDialogs } from '@/components/run/ReviewDialogs'
import { actionShortcut, approvalBlock, reviewActions } from '@/components/run/reviewActions'
import { StageTimeline } from '@/components/run/StageTimeline'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { FieldKey } from '@/lib/invoiceFields'
import { mergeRun } from '@/lib/runReducer'
import { useShortcuts, type Shortcut } from '@/lib/shortcuts'

type Detail = Schemas['RunDetail']
type Action = Schemas['ActionType']
const tabLabels = { decision: 'Decision', fields: 'Fields', matching: 'Matching', audit: 'Audit' }
type RunTab = keyof typeof tabLabels

export function RunView() {
  const { id = '' } = useParams()
  const preview = USE_MOCKS && /^S\d{2}$/.test(id)
  const alias = useQuery({
    queryKey: ['mock-scenario', id],
    queryFn: async () => (await import('@/mocks/mockServer')).openMockScenario(id),
    enabled: preview,
    staleTime: Infinity,
    retry: false,
  })
  const number = preview ? alias.data : /^\d+$/.test(id) ? Number(id) : undefined
  if (preview && alias.isPending) return <RunSkeleton />
  if (alias.isError) return <ErrorState title="Could not open this demo scenario" error={alias.error} retry={() => void alias.refetch()} />
  if (number === undefined || !Number.isSafeInteger(number) || number < 1) {
    return <EmptyState title="Invoice run not found"><Link className="text-link" to="/runs">View runs</Link></EmptyState>
  }
  return <RunLoader key={number} id={number} preview={preview} />
}

function RunSkeleton() {
  return <div className="grid gap-px bg-border xl:h-full xl:grid-cols-[300px_minmax(0,1fr)_420px]">
    {['Timeline', 'Document', 'Decision'].map(label => <section key={label} className="min-h-60 bg-card"><LoadingState label={'Loading ' + label.toLowerCase()} /></section>)}
  </div>
}

function RunLoader({ id, preview }: { id: number; preview: boolean }) {
  const query = useRun(id)
  if (query.data) return <RunWorkspace run={query.data} preview={preview} />
  if (query.isError) return <ErrorState title="Could not load the invoice run" error={query.error} retry={() => void query.refetch()} />
  return <RunSkeleton />
}

function saveFile(blob: Blob, filename?: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  if (filename) link.download = filename
  else { link.target = '_blank'; link.rel = 'noopener noreferrer' }
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

function RunWorkspace({ run: snapshot, preview }: { run: Detail; preview: boolean }) {
  const cache = useQueryClient()
  const navigate = useNavigate()
  const setLive = useContext(RunConnection)
  const [pace] = useState(preview || snapshot.status === 'running' || snapshot.status === 'queued')
  const { progress, connection, resume, animate } = useRunProgress(snapshot.id, pace, snapshot.review_actions.at(-1)?.created_at)
  const run = mergeRun(snapshot, progress, animate)
  const health = useHealth()
  const all = useAllRuns()
  const index = all.data?.findIndex(item => item.id === run.id) ?? -1
  const previous = index >= 0 ? all.data?.[index + 1]?.id : undefined
  const next = index > 0 ? all.data?.[index - 1]?.id : undefined
  const [field, setField] = useState<FieldKey | null>(null)
  const [action, setAction] = useState<Action | null>(null)
  const [tab, setTab] = useState<RunTab>('decision')
  const [sheet, setSheet] = useState(false)
  const running = run.status === 'running' || run.status === 'queued'
  const tabKeys = Object.keys(tabLabels) as RunTab[]
  useEffect(() => {
    setLive?.(running && connection === 'connected')
    return () => setLive?.(false)
  }, [setLive, running, connection])

  const audit = useMutation({
    mutationFn: () => api.getRunAudit(run.id),
    onSuccess: data => saveFile(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }), run.display_id + '-audit.json'),
  })
  const original = useMutation({
    mutationFn: async () => (await import('@/mocks/mockDocument')).mockOriginalPdf(run.id),
    onSuccess: blob => saveFile(blob),
  })
  function openOriginal() {
    if (USE_MOCKS) original.mutate()
    else window.open(runDocumentUrl(run.id), '_blank', 'noopener,noreferrer')
  }
  function reviewed(updated: Detail) {
    cache.setQueryData(queryKeys.run(run.id), updated)
    void cache.invalidateQueries({ queryKey: queryKeys.run(run.id) })
    resume(updated.review_actions.at(-1)?.created_at)
  }
  function go(id: number) { void navigate('/runs/' + id) }
  function selectTab(nextTab: RunTab, openSheet = false) {
    setField(null)
    setTab(nextTab)
    if (openSheet && window.innerWidth < 1280) setSheet(true)
  }
  function ask(action: Action) {
    if (!reviewActions(run).includes(action) || (action === 'approve' && approvalBlock(run))) return
    setAction(action)
  }
  const reviewKeys = Object.fromEntries(reviewActions(run).flatMap(action => {
    const shortcut = actionShortcut(action)
    return shortcut ? [[shortcut, () => ask(action)]] : []
  })) as Partial<Record<Shortcut, () => void>>
  useShortcuts({
    ...reviewKeys,
    decision: () => selectTab('decision', true), fields: () => selectTab('fields', true),
    matching: () => selectTab('matching', true), audit: () => selectTab('audit', true),
    prevRun: () => { if (previous) go(previous) }, nextRun: () => { if (next) go(next) },
  }, !action, 'run-evidence')

  const tabs = () => <Tabs value={tab} onValueChange={value => selectTab(value as RunTab)} className="flex h-full min-h-0 min-w-0 flex-col gap-0">
    <TabsList variant="line" className="grid h-9 w-full shrink-0 grid-cols-4 rounded-none border-b bg-card px-1 py-0">
      {tabKeys.map(key => <TabsTrigger key={key} value={key}
        className="h-full rounded-none border-0 border-b-2 border-transparent px-1 text-meta shadow-none! after:hidden data-[state=active]:border-b-primary! data-[state=active]:bg-card! data-[state=active]:text-primary!">
        {tabLabels[key]}<ShortcutHint id={key} />
      </TabsTrigger>)}
    </TabsList>
    <div className="min-h-0 min-w-0 flex-1 overflow-y-auto p-2.5">
      <TabsContent value="decision"><DecisionPanel run={run} onAction={ask} onHighlight={setField} /></TabsContent>
      <TabsContent value="fields"><FieldsPanel extraction={run.extraction} onHighlight={setField} /></TabsContent>
      <TabsContent value="matching"><MatchingPanel run={run} /></TabsContent>
      <TabsContent value="audit"><AuditPanel run={run} events={progress.events} download={() => audit.mutate()} /></TabsContent>
    </div>
  </Tabs>

  return <div className="flex min-h-full flex-col xl:h-full xl:min-h-0">
    <PageActions>
      <span className="hidden max-w-56 truncate text-meta text-muted-foreground md:inline" title={run.filename}>{run.filename}</span>
      {run.source === 'demo' && <Link className="text-link text-meta" to="/inbox">Inbox</Link>}
    </PageActions>
    <RecordBar run={run} prev={previous} next={next} navigate={go} download={() => audit.mutate()} downloading={audit.isPending} original={openOriginal} />
    {running && connection === 'retrying' && <p role="status" className="border-b bg-card px-3 py-1 text-meta text-hold">Reconnecting to live updates…</p>}
    {audit.isError && <ErrorState title="Could not download the audit" error={audit.error} retry={() => audit.mutate()} />}
    {original.isError && <ErrorState title="Could not open the invoice PDF" error={original.error} retry={() => original.mutate()} />}
    <div className="grid min-h-0 flex-1 gap-px bg-border md:grid-cols-[minmax(230px,0.85fr)_minmax(0,2fr)] xl:grid-cols-[300px_minmax(0,1fr)_420px]">
      <StageTimeline run={run} progress={progress} onHighlight={setField} />
      <DocumentViewer run={run} active={field} ocrAvailable={health.data?.health.ocr_available} original={openOriginal} />
      <section aria-label="Decision and evidence" className="hidden min-h-0 min-w-0 overflow-hidden bg-card xl:block">{tabs()}</section>
    </div>
    <div className="sticky bottom-0 flex justify-end border-t bg-card p-2 xl:hidden">
      <Button type="button" onClick={() => setSheet(true)}><PanelBottom aria-hidden="true" />Decision and evidence</Button>
      <Sheet open={sheet} onOpenChange={setSheet}>
        <SheetContent side="bottom" data-shortcut-scope="run-evidence" className="h-[78dvh] max-h-[88dvh] gap-0 overflow-hidden">
          <SheetHeader className="sr-only"><SheetTitle>Decision and evidence</SheetTitle><SheetDescription>Review invoice fields, matching and the event log.</SheetDescription></SheetHeader>
          <div className="min-h-0 flex-1 pt-10">{tabs()}</div>
        </SheetContent>
      </Sheet>
    </div>
    <ReviewDialogs action={action} run={run} onClose={() => setAction(null)} onReviewed={reviewed} />
  </div>
}
