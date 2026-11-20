import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ScanLine } from 'lucide-react'
import { runPageUrl, USE_MOCKS, type Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { fieldKeys, fieldLabels, type FieldKey, type InvoiceEvidence } from '@/lib/invoiceFields'
import { useShortcuts } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'
import { DocumentToolbar, type Zoom } from './DocumentToolbar'
import { HighlightLayer } from './HighlightLayer'

export function DocumentViewer({ run, active, evidence, ocrAvailable, original }: {
  evidence?: InvoiceEvidence | null; run: Schemas['RunDetail']; active: FieldKey | null; ocrAvailable?: boolean; original: () => void
}) {
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState<Zoom>('Fit')
  const [showAll, setShowAll] = useState(false)
  const [errorSrc, setErrorSrc] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const scale = zoom === '150%' ? 2.25 : 1.5
  const url = useQuery({
    queryKey: ['run-page', run.id, page, scale, attempt],
    queryFn: async () => USE_MOCKS ? (await import('@/mocks/mockDocument')).mockPageImage(run.id, page) :
      runPageUrl(run.id, page, scale) + (attempt ? '&retry=' + attempt : ''),
    enabled: run.page_count > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  })
  const extraction = run.extraction
  const highlightedPage = active && extraction ? extraction[active].bbox[0]?.page : evidence?.bbox[0]?.page
  useEffect(() => { if (highlightedPage) setPage(highlightedPage) }, [highlightedPage])
  useEffect(() => {
    if (evidence && !url.isPlaceholderData) {
      document.querySelector('[data-highlight="' + evidence.id + '"]')?.scrollIntoView({ block: 'center', inline: 'nearest' })
    }
  }, [evidence, url.data, url.isPlaceholderData])
  const highlights: InvoiceEvidence[] = extraction ? fieldKeys.map(id => ({
    id, label: fieldLabels[id], level: extraction[id].level, bbox: extraction[id].bbox,
  })) : []
  if (evidence && !highlights.some(item => item.id === evidence.id)) highlights.push(evidence)
  const readDetail = run.stages.find(row => row.name === 'read_document')?.detail
  const pageDetails = Array.isArray(readDetail?.pages) ? readDetail.pages[page - 1] as { kind?: string; ocr_used?: boolean } | undefined : undefined
  const scanned = pageDetails?.kind === 'scanned' || run.doc_kind === 'scanned'
  const noOcr = scanned && (pageDetails?.ocr_used ?? readDetail?.ocr_used ?? ocrAvailable) === false
  const toggle = () => setShowAll(value => !value)
  useShortcuts({ highlights: toggle })

  return <section aria-label="Invoice document" className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-muted">
    <DocumentToolbar page={page} pages={run.page_count} setPage={setPage} zoom={zoom} setZoom={setZoom} highlights={showAll} toggleHighlights={toggle} original={original} />
    {noOcr && <Alert className="rounded-none border-0 border-b bg-card text-hold">
      <ScanLine aria-hidden="true" /><AlertDescription>Scanned image. The model read the values without a text layer to check them against.</AlertDescription>
    </Alert>}
    {run.page_count > 1 && <nav aria-label="Invoice pages" className="flex shrink-0 gap-2 overflow-x-auto border-b bg-card p-2">
      {Array.from({ length: run.page_count }, (_, i) => i + 1).map(index => <Button type="button" key={index} size="sm"
        variant={index === page ? 'secondary' : 'outline'} aria-pressed={index === page} onClick={() => setPage(index)}>
        {!USE_MOCKS && <img alt="" src={runPageUrl(run.id, index, 0.5)} className="h-5 w-4 border object-contain" loading="lazy" />}
        Page {index}
      </Button>)}
    </nav>}
    <div className="min-h-52 flex-1 overflow-auto p-3 xl:min-h-0">
      {run.page_count === 0 ? <EmptyState title="Waiting for the invoice page" /> :
        url.isPending ? <LoadingState label="Loading the invoice page" /> :
          url.isError || (url.data && errorSrc === url.data) ? <ErrorState title="Could not display the invoice page"
            retry={() => { setErrorSrc(null); setAttempt(value => value + 1) }} /> :
            url.data && <figure className={cn('relative mx-auto border bg-white', zoom === 'Fit' && 'w-full max-w-[820px]',
              zoom === '100%' && 'w-[820px] max-w-none', zoom === '150%' && 'w-[1230px] max-w-none')}>
              <img src={url.data} alt={'Page ' + page + ' of ' + run.filename} className="block h-auto w-full" onError={() => setErrorSrc(url.data)} />
              {!url.isPlaceholderData && <HighlightLayer highlights={highlights} page={page} active={active ?? evidence?.id ?? null} showAll={showAll} />}
            </figure>}
    </div>
  </section>
}
