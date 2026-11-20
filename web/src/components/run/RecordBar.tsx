import { ChevronLeft, ChevronRight, Download, FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Schemas } from '@/api/client'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { RunStatusChip } from '@/components/StatusChip'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Button } from '@/components/ui/button'
import { duration, inr, istDate, istTime } from '@/lib/format'
import { sources } from '@/lib/labels'
import { effectiveOutcome } from '@/lib/runList'

export function RecordBar({ run, prev, next, navigate, download, downloading, original }: {
  run: Schemas['RunDetail']; prev?: number; next?: number; navigate: (id: number) => void
  download: () => void; downloading: boolean; original: () => void
}) {
  const outcome = effectiveOutcome(run)
  return <div className="flex h-10 shrink-0 items-center justify-between gap-2 overflow-hidden border-b bg-card px-3">
    <div className="flex h-full min-w-0 items-center overflow-x-auto whitespace-nowrap [scrollbar-width:none]">
      <div className="shrink-0 pr-2">{outcome ? <OutcomeBadge outcome={outcome} /> : <RunStatusChip status={run.status} />}</div>
      <dl className="flex h-full items-center divide-x border-l text-meta [&>div]:flex [&>div]:h-6 [&>div]:min-w-0 [&>div]:shrink-0 [&>div]:items-center [&>div]:gap-1.5 [&>div]:px-2 [&_dt]:text-muted-foreground">
        <div><dt>Vendor</dt><dd title={run.vendor_name ?? undefined} className="max-w-[110px] truncate font-medium">{run.vendor_name ?? 'Unknown vendor'}</dd></div>
        <div><dt>Invoice #</dt><dd className="identifier max-w-[98px] truncate" title={run.invoice_number ?? undefined}>{run.invoice_number ?? '—'}</dd></div>
        <div><dt>Amount</dt><dd className="font-medium">{inr(run.total)}</dd></div>
        <div><dt>PO</dt><dd className="identifier">{run.po_number ? <Link className="text-link" to={'/purchase-orders/' + encodeURIComponent(run.po_number)}>{run.po_number}</Link> : '—'}</dd></div>
        <div><dt>Received</dt><dd title={istDate(run.created_at) + ' · ' + istTime(run.created_at)}>{istTime(run.created_at)}</dd></div>
        <div><dt>Duration</dt><dd>{duration(run.duration_ms)}</dd></div>
        <div><dt className="sr-only">Source</dt><dd>{sources[run.source]}</dd></div>
        {run.cached_extraction && <div><dt className="sr-only">Extraction cache</dt><dd className="rounded-sm border bg-muted px-1.5 text-muted-foreground">Cached</dd></div>}
      </dl>
    </div>
    <div className="flex shrink-0 items-center gap-1">
      <Button variant="ghost" size="sm" aria-label="Previous run" title="Previous run" disabled={!prev} onClick={() => prev && navigate(prev)}><ChevronLeft /><ShortcutHint id="prevRun" className="hidden lg:inline-flex" /></Button>
      <Button variant="ghost" size="sm" aria-label="Next run" title="Next run" disabled={!next} onClick={() => next && navigate(next)}><ChevronRight /><ShortcutHint id="nextRun" className="hidden lg:inline-flex" /></Button>
      <Button variant="outline" size="sm" disabled={downloading} aria-label="Download audit JSON" title="Download audit JSON" onClick={download}><Download /><span className="hidden xl:inline">Audit JSON</span></Button>
      <Button variant="outline" size="sm" aria-label="Open original PDF" title="Open original PDF" onClick={original}><FileText /><span className="hidden xl:inline">Original PDF</span></Button>
    </div>
  </div>
}
