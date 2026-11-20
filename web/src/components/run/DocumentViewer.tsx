import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { FileText, Maximize2, ScanLine } from 'lucide-react'
import { runPageUrl, USE_MOCKS, type Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { fieldKeys, fieldLabels, type FieldKey } from '@/lib/invoiceFields'
import { cn } from '@/lib/utils'
import { HighlightLayer } from './HighlightLayer'

const levels = ['Fit width', '100%', '150%'] as const

export function DocumentViewer({ run, active, ocrAvailable }: {
  run: Schemas['RunDetail']; active: FieldKey | null; ocrAvailable?: boolean
}) {
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState<(typeof levels)[number]>('Fit width')
  const [showAll, setShowAll] = useState(false)
  const [errorSrc, setErrorSrc] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const scale = zoom === '150%' ? 2.25 : 1.5
  const url = useQuery({
    queryKey: ['run-page', run.id, page, scale, attempt],
    queryFn: async () => USE_MOCKS ? (await import('@/mocks/mockDocument')).mockPageImage(run.id, page) :
      runPageUrl(run.id, page, scale) + (attempt ? `&retry=${attempt}` : ''),
    enabled: run.page_count > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  })
  const extraction = run.extraction
  const highlightedPage = active && extraction ? extraction[active].bbox[0]?.page : undefined
  useEffect(() => { if (highlightedPage) setPage(highlightedPage) }, [highlightedPage])
  const highlights = extraction ? fieldKeys.map(id => ({
    id, label: fieldLabels[id], level: extraction[id].level, bbox: extraction[id].bbox,
  })) : []
  const readDetail = run.stages.find(row => row.name === 'read_document')?.detail
  const pageDetails = Array.isArray(readDetail?.pages) ? readDetail.pages[page - 1] as { kind?: string; ocr_used?: boolean } | undefined : undefined
  const scanned = pageDetails?.kind === 'scanned' || run.doc_kind === 'scanned'
  const noOcr = scanned && (pageDetails?.ocr_used ?? readDetail?.ocr_used ?? ocrAvailable) === false

  return <section className="panel flex min-h-0 min-w-0 flex-col overflow-hidden">
    <header className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2.5">
      <h2 className="section-title flex items-center gap-1.5"><FileText aria-hidden="true" className="size-4 text-indigo-700" />Invoice PDF</h2>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs font-medium text-slate-700">
          <Checkbox checked={showAll} onCheckedChange={checked => setShowAll(checked === true)} />Show all highlights
        </label>
        <label className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-slate-700">
          <Maximize2 className="size-3.5" aria-hidden="true" />
          <span className="sr-only">Document zoom</span>
          <select value={zoom} onChange={event => setZoom(event.target.value as typeof zoom)} className="rounded-sm bg-white">
            {levels.map(level => <option key={level}>{level}</option>)}
          </select>
        </label>
      </div>
    </header>
    {noOcr && <Alert className="rounded-none border-0 border-b border-amber-200 bg-amber-50 text-amber-900">
      <ScanLine aria-hidden="true" /><AlertDescription className="text-amber-900">Scanned image — values were read by the model. There’s no text layer to check them against.</AlertDescription>
    </Alert>}
    {run.page_count > 1 && <nav aria-label="Invoice pages" className="flex gap-2 overflow-x-auto border-b px-3 py-2">
      {Array.from({ length: run.page_count }, (_, i) => i + 1).map(index => <Button type="button" key={index} size="sm"
        variant={index === page ? 'secondary' : 'outline'} aria-pressed={index === page} onClick={() => setPage(index)}>
        {!USE_MOCKS && <img alt="" src={runPageUrl(run.id, index, 0.5)} className="h-5 w-4 border object-contain" loading="lazy" />}
        Page {index}
      </Button>)}
    </nav>}
    <div className="min-h-96 flex-1 overflow-auto bg-slate-100 p-4 xl:max-h-[calc(100vh-235px)]">
      {run.page_count === 0 ? <EmptyState title="Waiting for the invoice page" /> :
        url.isPending ? <LoadingState label="Loading the invoice page" /> :
          url.isError || (url.data && errorSrc === url.data) ? <ErrorState title="Could not display the invoice page"
            retry={() => { setErrorSrc(null); setAttempt(value => value + 1) }} /> :
            url.data && <figure className={cn('relative mx-auto bg-white shadow-md', zoom === 'Fit width' && 'w-full max-w-[820px]',
              zoom === '100%' && 'w-[820px] max-w-none', zoom === '150%' && 'w-[1230px] max-w-none')}>
              <img src={url.data} alt={`Page ${page} of ${run.filename}`} className="block h-auto w-full"
                onError={() => setErrorSrc(url.data)} />
              {!url.isPlaceholderData && <HighlightLayer highlights={highlights} page={page} active={active} showAll={showAll} />}
            </figure>}
    </div>
  </section>
}
