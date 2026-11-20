import { ListChecks, RotateCcw } from 'lucide-react'
import type { Schemas } from '@/api/client'
import type { FieldKey } from '@/lib/invoiceFields'
import { pendingStage, resumeStage, stageOrder, type RunProgress } from '@/lib/runReducer'
import { StageRow } from './StageRow'

export function StageTimeline({ run, progress, onHighlight }: {
  run: Schemas['RunDetail']; progress: RunProgress; onHighlight: (field: FieldKey | null) => void
}) {
  const updates = progress.events.at(-1)
  const completed = run.stages.filter(stage => stage.finished_at || stage.status === 'skipped').length
  const marker = progress.resumedMarkers.at(-1)
  return <section className="panel min-w-0 overflow-hidden">
    <header className="flex items-center justify-between gap-2 border-b px-3 py-2.5">
      <h2 className="section-title flex items-center gap-1.5"><ListChecks aria-hidden="true" className="size-4 text-indigo-700" />Stage timeline</h2>
      <span className="text-xs text-muted-foreground tabular-nums">{completed} of {stageOrder.length} steps</span>
    </header>
    <span className="sr-only" aria-live="polite" aria-atomic="true">{updates?.message ?? ''}</span>
    <div className="divide-y xl:max-h-[calc(100vh-235px)] xl:overflow-y-auto">
      {stageOrder.map(name => {
        const stage = run.stages.find(row => row.name === name) ?? pendingStage(name)
        return <div key={name}>
          {marker && name === resumeStage && <div className="flex items-start gap-2 border-b bg-indigo-50 px-3 py-2 text-xs font-medium text-indigo-900">
            <RotateCcw aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
            {marker.review && !marker.message.includes(marker.review.reviewer) ?
              `Resumed after review by ${marker.review.reviewer}${marker.review.po_number ? ` · confirmed ${marker.review.po_number}` : ''}` :
              marker.message}
          </div>}
          <StageRow stage={stage} checks={run.checks.filter(check => check.stage === stage.name)}
            log={progress.lastLog?.stage === stage.name ? progress.lastLog.message : null} onHighlight={onHighlight} />
        </div>
      })}
    </div>
  </section>
}
