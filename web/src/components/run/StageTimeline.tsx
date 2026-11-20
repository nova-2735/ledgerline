import { useState } from 'react'
import { ArrowDown, ArrowUp, RotateCcw } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Button } from '@/components/ui/button'
import { stages } from '@/lib/labels'
import { istTime } from '@/lib/format'
import type { FieldKey } from '@/lib/invoiceFields'
import { pendingStage, resumeStage, stageOrder, type RunProgress } from '@/lib/runReducer'
import { rowIndex, useShortcuts } from '@/lib/shortcuts'
import { StageRow } from './StageRow'

export function StageTimeline({ run, progress, onHighlight }: {
  run: Schemas['RunDetail']; progress: RunProgress; onHighlight: (field: FieldKey | null) => void
}) {
  const [expanded, setExpanded] = useState(-1)
  const updates = progress.events.at(-1)
  const completed = run.stages.filter(stage => stage.finished_at || stage.status === 'skipped').length
  const marker = progress.resumedMarkers.at(-1)
  const point = marker ? progress.events.find(event => event.seq === marker.seq)?.data?.from_stage ?? resumeStage : null

  function step(direction: 'previous' | 'next') {
    const index = rowIndex(expanded, stageOrder.length, direction)
    setExpanded(index)
    document.getElementById('stage-toggle-' + stageOrder[index])?.focus({ preventScroll: true })
    document.getElementById('stage-toggle-' + stageOrder[index])?.scrollIntoView?.({ block: 'nearest' })
  }

  useShortcuts({ prevStage: () => step('previous'), nextStage: () => step('next') })

  return <section className="flex min-h-0 min-w-0 flex-col bg-card" aria-label="Stage timeline">
    <header className="panel-title shrink-0">
      <h2>Stage timeline</h2>
      <div className="flex items-center gap-0.5">
        <span className="mr-1 text-meta font-normal text-muted-foreground">{completed} / {stageOrder.length}</span>
        <Button variant="ghost" size="icon-sm" title="Expand previous stage" aria-label="Expand previous stage" onClick={() => step('previous')}><ArrowUp className="sr-only" /><ShortcutHint id="prevStage" /></Button>
        <Button variant="ghost" size="icon-sm" title="Expand next stage" aria-label="Expand next stage" onClick={() => step('next')}><ArrowDown className="sr-only" /><ShortcutHint id="nextStage" /></Button>
      </div>
    </header>
    <span className="sr-only" aria-live="polite" aria-atomic="true">{updates?.message ?? (updates?.stage ? stages[updates.stage] : '')}</span>
    <div className="min-h-0 flex-1 overflow-y-auto">
      {stageOrder.map((name, index) => {
        const stage = run.stages.find(row => row.name === name) ?? pendingStage(name)
        return <div key={name}>
          {marker && name === point && <div data-testid="resume-divider" className="flex items-center gap-1.5 border-y bg-accent px-2.5 py-2 text-meta text-primary">
            <RotateCcw aria-hidden="true" className="size-3 shrink-0" />
            <span title={marker.message}>{marker.review ? 'Resumed · ' + marker.review.reviewer +
              (marker.review.po_number ? ' confirmed ' + marker.review.po_number : '') : marker.message} · {istTime(marker.ts)}</span>
          </div>}
          <StageRow stage={stage} index={index} expanded={index === expanded} toggle={() => setExpanded(index === expanded ? -1 : index)}
            checks={run.checks.filter(check => check.stage === stage.name)}
            log={progress.lastLog?.stage === stage.name ? progress.lastLog.message : null} onHighlight={onHighlight} />
        </div>
      })}
    </div>
  </section>
}
