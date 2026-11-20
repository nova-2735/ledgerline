import { useRef, useState, type DragEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ClipboardList, FileText, Layers3, Mail, ScanText, UploadCloud } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api, type Schemas } from '@/api/client'
import { queryKeys, useInbox, useRun } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { istDate, istTime } from '@/lib/format'
import { cn } from '@/lib/utils'

function InboxItem({ item, process, processing, disabled }: {
  item: Schemas['DemoInboxItem']
  process: () => void
  processing: boolean
  disabled: boolean
}) {
  const runId = item.processed_run_ids.at(-1)
  const run = useRun(runId ?? 0)
  const initials = item.sender_name.split(/\s+/).filter(word => /^[a-z]/i.test(word)).slice(0, 2).map(word => word[0]).join('')
  return <li className="flex flex-wrap items-start gap-3 px-4 py-4 sm:flex-nowrap sm:px-5">
    <span aria-hidden="true" className="grid size-10 shrink-0 place-items-center rounded-full bg-indigo-50 text-xs font-semibold text-indigo-800">
      {initials}
    </span>
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="text-sm font-semibold">{item.sender_name}</h3>
        <time dateTime={item.received_at} className="text-xs text-muted-foreground tabular-nums">{istDate(item.received_at)} · {istTime(item.received_at)}</time>
      </div>
      <p className="mt-1 text-sm font-medium text-slate-800">{item.subject}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="inline-flex min-w-0 items-center gap-1 rounded-md border px-1.5 py-1 text-xs text-muted-foreground">
          <FileText aria-hidden="true" className="size-3.5 shrink-0" /><span className="truncate">{item.filename}</span>
        </span>
        {item.tags.map(tag => <span key={tag} className="rounded-md bg-slate-100 px-1.5 py-1 text-xs font-medium text-slate-700">{tag}</span>)}
        {run.data?.outcome && <OutcomeBadge outcome={run.data.final_outcome ?? run.data.outcome} />}
      </div>
    </div>
    <div className="ml-auto grid shrink-0 justify-items-end gap-2">
      <Button size="sm" type="button" variant={runId ? 'outline' : 'default'} disabled={disabled} onClick={process}
        aria-label={`${runId ? 'Process again' : 'Process'} ${item.title}`}>
        {processing ? 'Starting…' : runId ? 'Process again' : 'Process'}
      </Button>
      {runId && <Link className="text-xs font-medium text-indigo-700 hover:underline" to={`/runs/${runId}`}>Open run</Link>}
    </div>
  </li>
}

const steps = [
  [ScanText, 'Read the invoice and its line items.'],
  [Layers3, 'Compare it with vendor records, orders and receipts.'],
  [ClipboardList, 'Check the totals, GST and duplicate history.'],
  [CheckCircle2, 'See the decision and who needs to act.'],
] as const

export function Inbox() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const inbox = useInbox()
  const input = useRef<HTMLInputElement>(null)
  const [forceFresh, setForceFresh] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadErrors, setUploadErrors] = useState<string[]>([])
  const invalidateActivity = () => {
    for (const key of [queryKeys.inbox, queryKeys.runs, queryKeys.stats, queryKeys.queue]) {
      void queryClient.invalidateQueries({ queryKey: key })
    }
  }
  const process = useMutation({
    mutationFn: (docId: string) => api.createDemoRun(docId, forceFresh),
    onSuccess: ({ run_id }) => { invalidateActivity(); void navigate(`/runs/${run_id}`) },
  })

  async function upload(files: File[]) {
    if (uploading || !files.length) return
    setUploading(true)
    setUploadErrors([])
    const result = await Promise.allSettled(files.map(async file => {
      if (!/\.pdf$/i.test(file.name)) throw new Error(`${file.name} must be a PDF.`)
      if (file.size > 10 * 1024 * 1024) throw new Error(`${file.name} exceeds the 10 MB limit.`)
      try {
        return await api.createRun(file, forceFresh)
      } catch (error) {
        throw new Error(`${file.name}: ${error instanceof Error ? error.message : 'Upload failed.'}`)
      }
    }))
    const accepted = result.flatMap(item => item.status === 'fulfilled' ? [item.value.run_id] : [])
    const errors = result.flatMap(item => item.status === 'rejected' ? [String(item.reason.message)] : [])
    setUploadErrors(errors)
    setUploading(false)
    if (accepted.length) {
      invalidateActivity()
      if (accepted.length > 1) toast.success(`${accepted.length} invoices queued`)
      if (errors.length) toast.error('Some invoices could not be uploaded', { description: errors.join(' ') })
      void navigate(`/runs/${accepted[0]}`)
    }
  }

  function drop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    void upload(Array.from(event.dataTransfer.files))
  }

  return <div className="space-y-4">
    <header>
      <h1 className="page-title">AP inbox</h1>
      <p className="mt-1 text-sm text-muted-foreground">Process an invoice from the demo inbox or upload your own PDF.</p>
    </header>
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <section className="panel">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3.5 sm:px-5">
          <h2 className="section-title flex items-center gap-2"><Mail aria-hidden="true" className="size-4 text-indigo-700" />Invoice emails</h2>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
            <Checkbox checked={forceFresh} onCheckedChange={checked => setForceFresh(checked === true)} />
            Force fresh read
          </label>
        </header>
        {inbox.isPending && <LoadingState label="Loading the inbox" />}
        {inbox.isError && <div className="p-4"><ErrorState title="Could not load the inbox" error={inbox.error} retry={() => void inbox.refetch()} /></div>}
        {process.isError && <div className="p-4"><ErrorState title="Could not start processing" error={process.error} /></div>}
        {inbox.data?.length === 0 && <EmptyState title="Your inbox is empty">Upload a PDF to start an invoice run.</EmptyState>}
        {!!inbox.data?.length && <ul className="divide-y">
          {inbox.data.map(item => <InboxItem key={item.doc_id} item={item} disabled={process.isPending}
            processing={process.isPending && process.variables === item.doc_id} process={() => process.mutate(item.doc_id)} />)}
        </ul>}
      </section>
      <aside className="space-y-4">
        <section className="panel p-5">
          <h2 className="section-title">Upload an invoice</h2>
          <div onDragOver={event => { event.preventDefault(); setDragging(true) }}
            onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false) }}
            onDrop={drop}
            className={cn('mt-3 grid justify-items-center gap-2 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center', dragging && 'border-indigo-500 bg-indigo-50')}>
            <span className="grid size-11 place-items-center rounded-lg bg-indigo-100 text-indigo-700"><UploadCloud aria-hidden="true" className="size-5" /></span>
            <p className="mt-1 text-sm font-medium">Drop one or more PDFs here</p>
            <p className="text-xs text-muted-foreground">Up to 10 MB and 10 pages per file</p>
            <input ref={input} type="file" accept=".pdf,application/pdf" multiple hidden onChange={event => {
              void upload(Array.from(event.target.files ?? []))
              event.target.value = ''
            }} />
            <Button type="button" variant="outline" className="mt-2" disabled={uploading} onClick={() => input.current?.click()}>
              {uploading ? 'Uploading…' : 'Choose PDFs'}
            </Button>
          </div>
          {!!uploadErrors.length && <ul role="alert" className="mt-3 space-y-1 text-sm text-rose-800">
            {uploadErrors.map((error, index) => <li key={index}>{error}</li>)}
          </ul>}
        </section>
        <section className="panel p-5">
          <h2 className="section-title">How it works</h2>
          <ul className="mt-3 grid gap-3 text-sm text-slate-700">
            {steps.map(([Icon, text]) => <li key={text} className="flex items-center gap-2.5">
              <Icon aria-hidden="true" className="size-4 shrink-0 text-indigo-700" />{text}
            </li>)}
          </ul>
        </section>
      </aside>
    </div>
  </div>
}
