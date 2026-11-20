import { useRef, useState } from 'react'
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
const rowHeight = 36
const viewport = 360

export function AuditPanel({ run, events, download }: {
  run: Schemas['RunDetail']; events: Schemas['RunEvent'][]; download: () => void
}) {
  const [position, setPosition] = useState(0)
  const [type, setType] = useState('')
  const table = useRef<HTMLDivElement>(null)
  const visible = type ? events.filter(event => event.type === type) : events
  const first = Math.max(0, Math.min(visible.length, Math.floor(position / rowHeight) - 2))
  const last = Math.min(visible.length, first + Math.ceil(viewport / rowHeight) + 5)
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-meta text-muted-foreground">Policy <span className="identifier text-foreground">{run.policy_version ?? '—'}</span></p>
      <Button type="button" size="sm" variant="outline" onClick={download}><Download aria-hidden="true" />Download audit JSON</Button>
    </div>
    <section className="panel">
      <header className="panel-title"><h3>Event log</h3>
        <select aria-label="Filter events by type" className="h-7 max-w-40 rounded-sm border bg-card px-1.5 text-meta font-normal" value={type}
          onChange={event => { setType(event.target.value); setPosition(0); if (table.current) table.current.scrollTop = 0 }}>
          <option value="">All event types</option>
          {Object.entries(eventNames).map(([key, title]) => <option key={key} value={key}>{title}</option>)}
        </select>
      </header>
      {visible.length ? <div ref={table} tabIndex={0} aria-label="Scrollable event log" className="overflow-auto" style={{ maxHeight: viewport }}
        onScroll={event => setPosition(event.currentTarget.scrollTop)}>
        <table aria-label="Run events" aria-rowcount={visible.length + 1} className="w-full min-w-[350px] table-fixed text-meta">
          <colgroup><col className="w-[61px]" /><col className="w-[101px]" /><col className="w-[93px]" /><col /></colgroup>
          <thead className="table-head"><tr>{['Time', 'Type', 'Stage', 'Message'].map(label => <th key={label} className="px-1.5 font-medium" scope="col">{label}</th>)}</tr></thead>
          <tbody>
            {!!first && <tr aria-hidden="true"><td colSpan={4} style={{ height: first * rowHeight }} /></tr>}
            {visible.slice(first, last).map((event, offset) => {
              const stage = event.stage ? stages[event.stage] : '—'
              return <tr key={event.seq} className="table-row" aria-rowindex={first + offset + 2}>
                <td className="px-1.5 text-muted-foreground"><time title={istDate(event.ts) + ' · ' + istTime(event.ts)} dateTime={event.ts}>{istTime(event.ts).replace(' IST', '')}</time></td>
                <td className="truncate px-1.5 font-medium" title={eventNames[event.type]}>{eventNames[event.type]}</td>
                <td className="truncate px-1.5 text-muted-foreground" title={stage}>{stage}</td>
                <td className="truncate px-1.5 text-muted-foreground" title={event.message ?? undefined}>{event.message ?? '—'}</td>
              </tr>
            })}
            {last < visible.length && <tr aria-hidden="true"><td colSpan={4} style={{ height: (visible.length - last) * rowHeight }} /></tr>}
          </tbody>
        </table>
      </div> : <p className="p-3 text-body text-muted-foreground">{type ? 'No events of this type.' : 'The event log appears when the run starts.'}</p>}
    </section>
    {!!run.review_actions.length && <section className="panel">
      <h3 className="panel-title">Review actions</h3>
      <ol className="divide-y">
        {run.review_actions.map(review => <li key={review.id} className="p-2.5">
          <strong>{actions[review.action]} · {review.reviewer}</strong>
          <time className="block text-meta text-muted-foreground" dateTime={review.created_at}>{istDate(review.created_at)} · {istTime(review.created_at)}</time>
          <p className="mt-1">{review.note}</p>
        </li>)}
      </ol>
    </section>}
    {run.extraction && <details className="panel p-2.5">
      <summary className="cursor-pointer font-medium">Raw model output</summary>
      <pre className="mt-2 max-h-72 overflow-auto bg-muted p-2 font-sans text-meta whitespace-pre-wrap wrap-anywhere">{JSON.stringify(run.extraction.meta.raw, null, 2)}</pre>
    </details>}
  </div>
}
