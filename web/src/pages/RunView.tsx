import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Circle, Download, FileText, PanelBottom } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { api, runDocumentUrl, USE_MOCKS, type Schemas } from '@/api/client'
import { queryKeys, useHealth, useRun } from '@/api/hooks'
import { useRunProgress } from '@/api/useRunProgress'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { SourceBadge } from '@/components/SourceBadge'
import { AuditPanel } from '@/components/run/AuditPanel'
import { DecisionPanel } from '@/components/run/DecisionPanel'
import { DocumentViewer } from '@/components/run/DocumentViewer'
import { FieldsPanel } from '@/components/run/FieldsPanel'
import { MatchingPanel } from '@/components/run/MatchingPanel'
import { ReviewDialogs } from '@/components/run/ReviewDialogs'
import { StageTimeline } from '@/components/run/StageTimeline'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { duration, inr, istTime } from '@/lib/format'
import type { FieldKey } from '@/lib/invoiceFields'
import { mergeRun } from '@/lib/runReducer'

type Detail = Schemas['RunDetail']
type Action = Schemas['ActionType']
const tabLabels = { decision: 'Decision', fields: 'Details', matching: 'Matching', audit: 'Audit' }
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
    return <EmptyState title="Invoice run not found"><Link className="text-indigo-700 underline" to="/">Go to dashboard</Link></EmptyState>
  }
  return <RunLoader key={number} id={number} preview={preview} />
}

function RunSkeleton() {
  return <div className="grid gap-3 xl:grid-cols-[320px_minmax(0,1fr)_440px]">
    <div className="panel xl:col-span-3"><LoadingState label="Loading invoice run" /></div>
    {['Timeline', 'Document', 'Decision'].map(label => <div key={label} className="panel min-h-60"><LoadingState label={`Loading ${label.toLowerCase()}`} /></div>)}
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
  const queryClient = useQueryClient()
  const [pace] = useState(preview || snapshot.status === 'running' || snapshot.status === 'queued')
  const { progress, connection, resume, animate } = useRunProgress(snapshot.id, pace)
  const run = mergeRun(snapshot, progress, animate)
  const health = useHealth()
  const [field, setField] = useState<FieldKey | null>(null)
  const [action, setAction] = useState<Action | null>(null)
  const [tab, setTab] = useState<RunTab>('decision')
  const running = run.status === 'running' || run.status === 'queued'
  const audit = useMutation({
    mutationFn: () => api.getRunAudit(run.id),
    onSuccess: data => saveFile(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }), `${run.display_id}-audit.json`),
  })
  const original = useMutation({
    mutationFn: async () => (await import('@/mocks/mockDocument')).mockOriginalPdf(run.id),
    onSuccess: blob => saveFile(blob),
  })
  function reviewed(updated: Detail) {
    queryClient.setQueryData(queryKeys.run(run.id), updated)
    void queryClient.invalidateQueries({ queryKey: queryKeys.run(run.id) })
    resume()
  }

  const tabs = () => <Tabs value={tab} onValueChange={value => { setField(null); setTab(value as RunTab) }} className="min-w-0 gap-0">
    <TabsList className="grid h-10 w-full grid-cols-4 rounded-none border-b bg-slate-50 px-2">
      {Object.entries(tabLabels).map(([key, label]) => <TabsTrigger key={key} value={key}>{label}</TabsTrigger>)}
    </TabsList>
    <div className="min-w-0 px-3 py-3 xl:max-h-[calc(100vh-233px)] xl:overflow-y-auto">
      <TabsContent value="decision"><DecisionPanel run={run} onAction={setAction} onHighlight={setField} /></TabsContent>
      <TabsContent value="fields"><FieldsPanel extraction={run.extraction} onHighlight={setField} /></TabsContent>
      <TabsContent value="matching"><MatchingPanel run={run} /></TabsContent>
      <TabsContent value="audit"><AuditPanel run={run} events={progress.events} download={() => audit.mutate()} /></TabsContent>
    </div>
  </Tabs>

  return <div className="space-y-3">
    <Link to={run.source === 'demo' ? '/inbox' : '/'} className="inline-flex items-center gap-1.5 text-sm font-medium text-indigo-700 hover:underline">
      <ArrowLeft aria-hidden="true" className="size-4" />{run.source === 'demo' ? 'AP inbox' : 'All runs'}
    </Link>
    <header className="panel flex flex-wrap items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <SourceBadge source={run.source} />
          <span className="text-xs font-medium text-muted-foreground tabular-nums">{run.display_id}</span>
          {running && <span className="status-chip bg-indigo-50 text-indigo-800"><Circle aria-hidden="true" className="fill-current" />Live</span>}
          {running && connection === 'retrying' && <span role="status" className="text-xs text-amber-800">Reconnecting to live updates…</span>}
          {run.outcome && <OutcomeBadge outcome={run.final_outcome ?? run.outcome} />}
        </div>
        <h1 title={run.filename} className="mt-1.5 text-xl leading-tight font-semibold tracking-tight wrap-anywhere">{run.filename}</h1>
        <p className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-sm text-muted-foreground tabular-nums">
          <strong className="font-medium text-slate-800">{run.vendor_name ?? 'Unknown vendor'}</strong>
          {run.invoice_number && <span>· {run.invoice_number}</span>}{run.total && <span>· {inr(run.total)}</span>}
          <span>· Received {istTime(run.created_at)}</span>{run.duration_ms != null && <span>· {duration(run.duration_ms)}</span>}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" disabled={audit.isPending} onClick={() => audit.mutate()}><Download aria-hidden="true" />Download audit (JSON)</Button>
        {USE_MOCKS ? <Button type="button" variant="outline" size="sm" disabled={original.isPending} onClick={() => original.mutate()}>
          <FileText aria-hidden="true" />Open original PDF
        </Button> : <Button asChild variant="outline" size="sm"><a href={runDocumentUrl(run.id)} target="_blank" rel="noreferrer">
          <FileText aria-hidden="true" />Open original PDF
        </a></Button>}
      </div>
    </header>
    {audit.isError && <ErrorState title="Could not download the audit" error={audit.error} retry={() => audit.mutate()} />}
    {original.isError && <ErrorState title="Could not open the invoice PDF" error={original.error} retry={() => original.mutate()} />}
    <div className="grid items-start gap-3 md:grid-cols-[minmax(270px,1fr)_minmax(0,2fr)] xl:grid-cols-[320px_minmax(0,1fr)_440px]">
      <StageTimeline run={run} progress={progress} onHighlight={setField} />
      <DocumentViewer run={run} active={field} ocrAvailable={health.data?.ocr_available} />
      <section aria-label="Decision and evidence" className="panel hidden min-w-0 overflow-hidden xl:block">{tabs()}</section>
    </div>
    <div className="sticky bottom-3 flex justify-end xl:hidden">
      <Sheet>
        <SheetTrigger asChild><Button className="shadow-md"><PanelBottom aria-hidden="true" />Decision and evidence</Button></SheetTrigger>
        <SheetContent side="bottom" className="max-h-[88dvh] gap-2 overflow-y-auto rounded-t-xl">
          <SheetHeader className="pb-1"><SheetTitle>Decision and evidence</SheetTitle><SheetDescription>Review invoice fields, matching and the event log.</SheetDescription></SheetHeader>
          {tabs()}
        </SheetContent>
      </Sheet>
    </div>
    <ReviewDialogs action={action} run={run} onClose={() => setAction(null)} onReviewed={reviewed} />
  </div>
}
