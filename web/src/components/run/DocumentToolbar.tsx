import { ChevronLeft, ChevronRight, ExternalLink, ScanLine } from 'lucide-react'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Button } from '@/components/ui/button'

export const zoomLevels = ['Fit', '100%', '150%'] as const
export type Zoom = typeof zoomLevels[number]

export function DocumentToolbar({ page, pages, setPage, zoom, setZoom, highlights, toggleHighlights, original }: {
  page: number; pages: number; setPage: (page: number) => void; zoom: Zoom; setZoom: (zoom: Zoom) => void
  highlights: boolean; toggleHighlights: () => void; original: () => void
}) {
  return <div className="flex min-h-9 shrink-0 flex-wrap items-center gap-1.5 border-b bg-card px-2 text-meta">
    <span className="mr-auto hidden font-medium lg:inline">Document</span>
    <div className="flex shrink-0 items-center gap-0.5">
      {pages > 1 && <Button type="button" size="icon-xs" variant="ghost" aria-label="Previous PDF page" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft /></Button>}
      <span className="text-muted-foreground">Page {pages ? page : '—'} / {pages}</span>
      {pages > 1 && <Button type="button" size="icon-xs" variant="ghost" aria-label="Next PDF page" disabled={page >= pages} onClick={() => setPage(page + 1)}><ChevronRight /></Button>}
    </div>
    <div className="flex divide-x rounded-sm border" aria-label="Document zoom">
      {zoomLevels.map(level => <button type="button" key={level} aria-pressed={zoom === level} className="h-6 px-1.5 hover:bg-muted aria-pressed:bg-accent aria-pressed:text-primary"
        onClick={() => setZoom(level)}>{level}</button>)}
    </div>
    <Button type="button" size="sm" variant="ghost" aria-label="Toggle highlights" aria-pressed={highlights} title="Toggle highlights" onClick={toggleHighlights}>
      <ScanLine className="size-3.5" aria-hidden="true" /><span className="hidden 2xl:inline">Highlights</span><ShortcutHint id="highlights" />
    </Button>
    <Button type="button" size="icon-xs" variant="ghost" title="Open original PDF" aria-label="Open original PDF from document toolbar" onClick={original}><ExternalLink /></Button>
  </div>
}
