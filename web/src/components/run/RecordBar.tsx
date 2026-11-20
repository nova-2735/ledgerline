import { ChevronLeft, ChevronRight, Download, FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { auditPdfUrl, supportsAuditPdf, type Schemas } from '@/api/client'
import { PageActions } from '@/components/layout/PageActions'
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
  const pdf = useQuery({
    queryKey: ['audit-pdf-support'],
    queryFn: ({ signal }) => supportsAuditPdf(run.id, signal),
    staleTime: Infinity, gcTime: Infinity,
  })
  const outcome = effectiveOutcome(run)
  return <><PageActions>
    <span className="hidden items-center gap-2 whitespace-nowrap text-meta text-muted-foreground lg:flex">
      <span>{sources[run.source]}</span><span title={istDate(run.created_at) + ' · ' + istTime(run.created_at)}>Received {istTime(run.created_at)}</span>
      <span>Duration {duration(run.duration_ms)}</span>{run.cached_extraction && <span className="border px-1">Cached</span>}
    </span>
  </PageActions><div className="flex h-10 shrink-0 items-center justify-between gap-2 overflow-hidden border-b bg-card px-3">
    <div className="flex h-full min-w-0 items-center overflow-x-auto whitespace-nowrap [scrollbar-width:none]">
      <div className="shrink-0 pr-1.5">{outcome ? <OutcomeBadge outcome={outcome} compact /> : <RunStatusChip status={run.status} />}</div>
      <dl className="flex h-full items-center divide-x border-l text-meta [&>div]:flex [&>div]:h-6 [&>div]:min-w-0 [&>div]:shrink-0 [&>div]:items-center [&>div]:gap-1 [&>div]:px-1.5 [&_dt]:text-muted-foreground">
        <div><dt>Vendor</dt><dd title={run.vendor_name ?? undefined} className="max-w-[90px] truncate font-medium">{run.vendor_name ?? 'Unknown vendor'}</dd></div>
        <div><dt>Invoice #</dt><dd className="identifier max-w-[110px] truncate" title={run.invoice_number ?? undefined}>{run.invoice_number ?? '—'}</dd></div>
        <div><dt>Amount</dt><dd className="font-medium">{inr(run.total)}</dd></div>
        <div><dt>PO</dt><dd className="identifier">{run.po_number ? <Link className="text-link" to={'/purchase-orders/' + encodeURIComponent(run.po_number)}>{run.po_number}</Link> : '—'}</dd></div>
      </dl>
    </div>
    <div className="flex shrink-0 items-center gap-1">
      <Button variant="ghost" size="sm" aria-label="Previous run" title="Previous run" disabled={!prev} onClick={() => prev && navigate(prev)}><ChevronLeft className="lg:hidden" /><ShortcutHint id="prevRun" className="hidden lg:inline-flex" /></Button>
      <Button variant="ghost" size="sm" aria-label="Next run" title="Next run" disabled={!next} onClick={() => next && navigate(next)}><ChevronRight className="lg:hidden" /><ShortcutHint id="nextRun" className="hidden lg:inline-flex" /></Button>
      <Button variant="outline" size="sm" disabled={downloading} aria-label="Download audit JSON" title="Download audit JSON" onClick={download}><Download /><span className="hidden xl:inline">Audit JSON</span></Button>
      {pdf.data ? <Button asChild variant="outline" size="sm"><a href={auditPdfUrl(run.id)} download><Download />Audit PDF</a></Button> :
        <span tabIndex={0} title={pdf.isPending ? 'Checking availability' : pdf.isError ? 'Could not check availability' : 'Available after backend update'}>
          <Button variant="outline" size="sm" disabled><Download />Audit PDF</Button>
        </span>}
      <Button variant="outline" size="sm" aria-label="Open original PDF" title="Open original PDF" onClick={original}><FileText /><span className="hidden xl:inline">Original PDF</span></Button>
    </div>
  </div></>
}
