import { useState } from 'react'
import { Download } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'
import { istDate, istTime } from '@/lib/format'
import { actions, stages } from '@/lib/labels'

const eventNames = {
  'run.created': 'Invoice received', 'run.started': 'Processing started', 'stage.started': 'Step started',
  'stage.log': 'Progress update', 'stage.completed': 'Step completed', 'decision.made': 'Decision made',
  'run.awaiting_review': 'Awaiting review', 'run.completed': 'Run completed', 'run.failed': 'Run failed',
  'review.recorded': 'Review recorded', 'run.resumed': 'Run resumed',
} satisfies Record<Schemas['RunEvent']['type'], string>
const rowHeight = 68
const viewport = 325

export function AuditPanel({ run, events, download }: {
  run: Schemas['RunDetail']; events: Schemas['RunEvent'][]; download: () => void
}) {
  const [position, setPosition] = useState(0)
  const first = Math.max(0, Math.floor(position / rowHeight) - 2)
  const last = Math.min(events.length, first + Math.ceil(viewport / rowHeight) + 5)
  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm"><strong>Policy</strong> {run.policy_version ?? '—'}</p>
      <Button type="button" size="sm" variant="outline" onClick={download}><Download aria-hidden="true" />Download audit JSON</Button>
    </div>
    <section className="overflow-hidden rounded-lg border">
      <h3 className="bg-slate-50 px-3 py-2 text-sm font-semibold">Event log</h3>
      {events.length ? <div tabIndex={0} aria-label="Scrollable event log" className="overflow-y-auto" style={{ maxHeight: viewport }}
        onScroll={event => setPosition(event.currentTarget.scrollTop)}>
        <ol className="relative" style={{ height: events.length * rowHeight }}>
          {events.slice(first, last).map((event, offset) => <li key={event.seq} aria-posinset={first + offset + 1} aria-setsize={events.length}
            className="absolute right-0 left-0 overflow-hidden border-b px-3 py-1.5 text-xs"
            style={{ top: (first + offset) * rowHeight, height: rowHeight }}>
            <p className="flex flex-wrap items-center gap-x-2"><time dateTime={event.ts} className="text-slate-600 tabular-nums">{istTime(event.ts)}</time>
              <strong>{eventNames[event.type]}</strong></p>
            {event.stage && <p className="text-slate-700">{stages[event.stage]}</p>}
            {event.message && <p className="truncate text-muted-foreground" title={event.message}>{event.message}</p>}
          </li>)}
        </ol>
      </div> : <p className="p-3 text-sm text-muted-foreground">The event log appears when the run starts.</p>}
    </section>
    {!!run.review_actions.length && <section className="space-y-2">
      <h3 className="section-title">Review actions</h3>
      <ol className="divide-y rounded-lg border text-sm">
        {run.review_actions.map(review => <li key={review.id} className="p-2.5">
          <strong>{actions[review.action]} · {review.reviewer}</strong>
          <time className="block text-xs text-muted-foreground" dateTime={review.created_at}>{istDate(review.created_at)} · {istTime(review.created_at)}</time>
          <p className="mt-1">{review.note}</p>
        </li>)}
      </ol>
    </section>}
    {run.extraction && <details className="rounded-lg border p-3 text-sm">
      <summary className="cursor-pointer font-medium">Raw model output</summary>
      <pre className="mt-2 max-h-80 overflow-auto rounded bg-slate-50 p-2 text-xs whitespace-pre-wrap wrap-anywhere">{JSON.stringify(run.extraction.meta.raw, null, 2)}</pre>
    </details>}
  </div>
}
