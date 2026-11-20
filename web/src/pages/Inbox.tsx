import { useRef, useState, type DragEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, Search, Upload } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { api, type Schemas } from '@/api/client'
import { queryKeys, useAllRuns, useInbox, useRun } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { OutcomeBadge, StatusSquare } from '@/components/OutcomeBadge'
import { RowKeys } from '@/components/RowKeys'
import { ShortcutHint } from '@/components/ShortcutHint'
import { WorkFolders } from '@/components/WorkFolders'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { inr, istDate, istTime } from '@/lib/format'
import { effectiveOutcome, type Run } from '@/lib/runList'
import { rowIndex, useShortcuts } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

type Mail = Schemas['DemoInboxItem']
type Item = { key: string; doc?: Mail; run?: Run }

const folders = [
  ['all', 'All'], ['new', 'Unprocessed'], ['processed', 'Processed'], ['edge', 'Edge cases'], ['uploaded', 'Uploaded'],
] as const

const outcomeTags = new Set(['approve', 'approved', 'hold', 'return', 'return-to-vendor', 'reject', 'expected-approve', 'expected-hold', 'expected-return', 'expected-reject'])
const shownTags = (mail?: Mail) => mail?.tags.filter(tag => !outcomeTags.has(tag.toLowerCase())) ?? []

function hasFolder(item: Item, folder: string) {
  if (folder === 'uploaded') return !item.doc
  if (!item.doc) return folder === 'all'
  if (folder === 'edge') return item.doc.is_edge_case
  if (folder === 'new') return !item.doc.processed_run_ids.length
  if (folder === 'processed') return !!item.doc.processed_run_ids.length
  return true
}

export function Inbox() {
  const cache = useQueryClient()
  const navigate = useNavigate()
  const messages = useInbox()
  const runs = useAllRuns(true)
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>()
  const [forceFresh, setForceFresh] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadErrors, setUploadErrors] = useState<string[]>([])
  const searchInput = useRef<HTMLInputElement>(null)
  const uploadInput = useRef<HTMLInputElement>(null)
  const preview = useRef<HTMLElement>(null)

  const folder = folders.find(([id]) => id === params.get('folder'))?.[0] ?? 'all'
  const byId = new Map(runs.data?.map(run => [run.id, run]))
  const mail: Item[] = (messages.data ?? []).map(doc => ({ key: doc.doc_id, doc, run: byId.get(doc.processed_run_ids.at(-1) ?? 0) }))
  const uploads: Item[] = (runs.data ?? []).filter(run => run.source === 'upload').map(run => ({ key: 'run-' + run.id, run }))
  const all = [...mail, ...uploads]
  const filtered = all.filter(item => hasFolder(item, folder) && [
    item.doc?.sender_name, item.doc?.subject, item.doc?.filename, item.doc?.title, item.run?.vendor_name, item.run?.display_id, item.run?.invoice_number,
  ].some(value => value?.toLowerCase().includes(search.trim().toLowerCase())))
  const entry = selected === null ? undefined : filtered.find(item => item.key === (selected ?? params.get('doc'))) ?? filtered[0]
  const currentId = entry?.doc?.processed_run_ids.at(-1) ?? entry?.run?.id
  const detail = useRun(currentId ?? 0)

  function invalidateActivity() {
    for (const queryKey of [queryKeys.inbox, queryKeys.runs, queryKeys.stats, queryKeys.queue]) void cache.invalidateQueries({ queryKey })
  }

  const process = useMutation({
    mutationFn: ({ id, fresh }: { id: string; fresh: boolean }) => api.createDemoRun(id, fresh),
    onSuccess: ({ run_id }) => { invalidateActivity(); void navigate('/runs/' + run_id) },
  })

  function processEntry(fresh: boolean) {
    if (entry?.doc && !process.isPending && !uploading) process.mutate({ id: entry.doc.doc_id, fresh: fresh || forceFresh })
  }

  async function upload(files: File[]) {
    if (uploading || process.isPending || !files.length) return
    setUploading(true)
    setUploadErrors([])
    const result = await Promise.allSettled(files.map(async file => {
      if (!/\.pdf$/i.test(file.name)) throw new Error(file.name + ' must be a PDF.')
      if (file.size > 10 * 1024 * 1024) throw new Error(file.name + ' exceeds the 10 MB limit.')
      try { return await api.createRun(file, forceFresh) }
      catch (error) { throw new Error(file.name + ': ' + (error instanceof Error ? error.message : 'Upload failed.')) }
    }))
    const accepted = result.flatMap(item => item.status === 'fulfilled' ? [item.value.run_id] : [])
    const errors = result.flatMap(item => item.status === 'rejected' ? [String(item.reason.message)] : [])
    setUploadErrors(errors)
    setUploading(false)
    if (accepted.length) {
      invalidateActivity()
      if (accepted.length > 1) toast.success(accepted.length + ' invoices queued')
      if (errors.length) toast.error('Some invoices could not be uploaded', { description: errors.join(' ') })
      void navigate('/runs/' + accepted[0])
    }
  }

  function drop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    void upload(Array.from(event.dataTransfer.files))
  }

  function step(direction: 'next' | 'previous') {
    const index = filtered.findIndex(item => item.key === entry?.key)
    const target = filtered[rowIndex(index, filtered.length, direction)]
    if (target) {
      setSelected(target.key)
      document.getElementById('mail-' + target.key)?.scrollIntoView?.({ block: 'nearest' })
    }
  }
  useShortcuts({
    search: () => searchInput.current?.focus(), next: () => step('next'), previous: () => step('previous'),
    open: () => { if (currentId) void navigate('/runs/' + currentId) },
    previewMessage: () => preview.current?.focus(),
    process: () => processEntry(false), fresh: () => processEntry(true),
    escape: () => setSelected(null),
  })
  const loading = folder === 'uploaded' ? runs.isPending : messages.isPending
  const error = folder === 'uploaded' ? runs.error : messages.error

  return <div className="page-padding h-full min-h-0">
    <div className="grid min-h-full grid-cols-1 gap-px border bg-border lg:h-full lg:min-h-0 lg:grid-cols-[200px_minmax(0,1.25fr)_minmax(265px,0.95fr)]">
      <WorkFolders title="Folders" folders={folders.map(([id, label]) => ({ id, label, count: all.filter(item => hasFolder(item, id)).length }))}
        active={folder} select={id => { setSelected(undefined); setParams(id === 'all' ? {} : { folder: id }) }} />
      <section aria-label="Messages" className={cn('flex min-h-0 min-w-0 flex-col bg-card', dragging && 'relative z-10 outline-2 -outline-offset-2 outline-primary')}
        onDragOver={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); setDragging(true) } }}
        onDragLeave={event => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false) }} onDrop={drop}>
        <div className="flex min-h-11 shrink-0 flex-wrap items-center gap-x-2 border-b bg-muted px-3">
          <Upload aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <span className="text-meta text-muted-foreground">Drop PDFs or</span>
          <button type="button" className="text-link text-meta font-medium" disabled={uploading || process.isPending} onClick={() => uploadInput.current?.click()}>{uploading ? 'Uploading…' : 'browse'}</button>
          <span className="text-meta text-muted-foreground" title="Maximum 10 pages per invoice">· ≤10 MB</span>
          <input ref={uploadInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={event => {
            void upload(Array.from(event.target.files ?? [])); event.target.value = ''
          }} />
          <label className="ml-auto flex items-center gap-1.5 text-meta text-muted-foreground"><Checkbox checked={forceFresh} onCheckedChange={checked => setForceFresh(checked === true)} />Force fresh read</label>
        </div>
        <div className="flex h-11 shrink-0 items-center gap-2 border-b px-2">
          <label className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" aria-hidden="true" />
            <Input ref={searchInput} value={search} onChange={event => { setSearch(event.target.value); setSelected(undefined) }} aria-label="Search inbox" placeholder="Search messages…" className="h-8 pl-8 pr-7 text-body" />
            <ShortcutHint id="search" className="pointer-events-none absolute top-2 right-2" />
          </label>
          <RowKeys onStep={step} disabled={!filtered.length} />
          <Button type="button" variant="ghost" size="sm" disabled={!entry} aria-label="Focus message preview" onClick={() => preview.current?.focus()}><ShortcutHint id="previewMessage" /></Button>
        </div>
        {!!uploadErrors.length && <ul className="space-y-1 border-b p-3 text-reject" role="alert">
          {uploadErrors.map((error, index) => <li key={index}>{error}</li>)}
        </ul>}
        {process.isError && <ErrorState title="Could not start processing" error={process.error} />}
        <div className="min-h-0 flex-1 overflow-auto">
          {loading ? <LoadingState label="Loading the inbox" /> : error ?
            <ErrorState title="Could not load the inbox" error={error} retry={() => void (folder === 'uploaded' ? runs.refetch() : messages.refetch())} /> :
            !filtered.length ? <EmptyState title={folder === 'uploaded' ? 'No uploaded invoices' : 'No messages in this folder'} /> :
              <ul className="divide-y">
                {filtered.map(item => {
                  const date = item.doc?.received_at ?? item.run?.created_at
                  const outcome = item.run && effectiveOutcome(item.run)
                  const active = item === entry
                  return <li key={item.key}><button type="button" id={'mail-' + item.key} onClick={() => setSelected(item.key)} aria-pressed={active}
                    className={cn('grid h-10 w-full min-w-0 grid-cols-[8px_minmax(80px,0.85fr)_minmax(120px,1.4fr)_auto_auto] items-center gap-2 px-3 text-left hover:bg-muted', active && 'bg-accent hover:bg-accent')}>
                    <StatusSquare outcome={outcome} className={!outcome && item.doc?.processed_run_ids.length ? 'bg-input' : undefined} />
                    <span className="truncate font-medium" title={item.doc?.sender_name ?? item.run?.vendor_name ?? undefined}>{item.doc?.sender_name ?? item.run?.vendor_name ?? 'Uploaded PDF'}</span>
                    <span className="truncate text-meta" title={item.doc?.subject ?? item.run?.filename}>{item.doc?.subject ?? item.run?.filename}</span>
                    <span className="hidden max-w-24 items-center gap-1 overflow-hidden xl:flex">
                      {shownTags(item.doc).filter(tag => tag !== 'digital').slice(0, 1).map(tag => <span key={tag} className="truncate rounded-sm border bg-card px-1 text-meta text-muted-foreground" title={tag}>{tag}</span>)}
                    </span>
                    {date && <time dateTime={date} className="whitespace-nowrap text-meta text-muted-foreground" title={istDate(date) + ' · ' + istTime(date)}>{istTime(date).replace(' IST', '')}</time>}
                  </button></li>
                })}
              </ul>}
        </div>
      </section>
      <section ref={preview} tabIndex={-1} aria-label="Message preview" className="min-h-0 min-w-0 overflow-auto bg-card">
        <h2 className="panel-title">Preview</h2>
        {!entry ? <EmptyState title="Choose a message" /> :
          <div className="space-y-4 p-4">
            <div>
              <div className="flex items-center gap-1.5 text-meta text-muted-foreground"><FileText className="size-3.5" aria-hidden="true" />
                {entry.doc ? <span className="identifier">{entry.doc.doc_id}</span> : <span>Uploaded invoice</span>}
              </div>
              <h3 className="mt-1 text-title">{entry.doc?.subject ?? entry.run?.filename}</h3>
            </div>
            <dl className="border-y text-meta [&>div]:grid [&>div]:min-h-8 [&>div]:grid-cols-[78px_minmax(0,1fr)] [&>div]:items-center [&>div]:gap-2 [&>div]:border-b [&>div]:py-1.5 [&>div:last-child]:border-b-0 [&_dt]:text-muted-foreground">
              <div><dt>From</dt><dd className="min-w-0 break-words">{entry.doc?.sender_name ?? entry.run?.vendor_name ?? 'Uploaded directly'}
                {entry.doc?.sender_email && <span className="block text-muted-foreground">{entry.doc.sender_email}</span>}</dd></div>
              <div><dt>Received</dt><dd>{istDate(entry.doc?.received_at ?? entry.run?.created_at)} · {istTime((entry.doc?.received_at ?? entry.run?.created_at)!)}</dd></div>
              <div><dt>Attachment</dt><dd className="truncate" title={entry.doc?.filename ?? entry.run?.filename}>{entry.doc?.filename ?? entry.run?.filename}</dd></div>
              <div><dt>Size</dt><dd>{fileSize(detail.data)}</dd></div>
            </dl>
            {shownTags(entry.doc).length > 0 && <div className="flex flex-wrap gap-1.5">{shownTags(entry.doc).map(tag => <span key={tag} className="rounded-sm border bg-muted px-1.5 py-0.5 text-meta text-muted-foreground">{tag}</span>)}</div>}
            {entry.doc && <section><h4 className="text-section">What’s tricky here</h4><p className="mt-1 text-body text-muted-foreground">{entry.doc.title}</p></section>}
            {currentId && <div className="flex items-center justify-between gap-2 border-t py-2">
              <div className="min-w-0"><div className="text-meta text-muted-foreground">{entry.doc ? 'Last run' : 'Invoice run'}</div>
                <OutcomeBadge outcome={detail.data ? effectiveOutcome(detail.data) : entry.run && effectiveOutcome(entry.run)} />
                {entry.run?.total && <span className="ml-2 text-meta">{inr(entry.run.total)}</span>}
              </div>
              <Button asChild size="sm" variant="outline"><Link to={'/runs/' + currentId}>{entry.doc ? 'Open last run' : 'Open run'}<ShortcutHint id="open" /></Link></Button>
            </div>}
            {entry.doc && <div className="flex flex-wrap items-center gap-2 border-t pt-3">
              <Button type="button" disabled={process.isPending || uploading} onClick={() => processEntry(false)}>
                {process.isPending ? 'Starting…' : currentId ? 'Process again' : 'Process'}<ShortcutHint id="process" />
              </Button>
              <Button type="button" variant="outline" disabled={process.isPending || uploading} onClick={() => processEntry(true)}>Process with fresh read<ShortcutHint id="fresh" /></Button>
            </div>}
          </div>}
      </section>
    </div>
  </div>
}

function fileSize(run?: Schemas['RunDetail']) {
  const bytes = run?.stages.find(stage => stage.name === 'intake')?.detail.bytes
  return typeof bytes === 'number' ? Math.max(1, Math.round(bytes / 1024)) + ' KB' : '—'
}
