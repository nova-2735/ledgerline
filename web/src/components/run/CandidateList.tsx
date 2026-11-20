import type { Schemas } from '@/api/client'
import { pct } from '@/lib/format'

export function CandidateList({ candidates }: { candidates: Schemas['POCandidate'][] }) {
  if (!candidates.length) return null
  return <section className="space-y-2">
    <h3 className="section-title">Possible purchase orders</h3>
    <ol className="divide-y rounded-lg border">
      {[...candidates].sort((a, b) => b.score - a.score).map(candidate => <li key={candidate.po_number} className="space-y-2 p-2.5 text-sm">
        <div className="flex justify-between gap-2 font-medium tabular-nums"><span>{candidate.po_number}</span><span>{pct(candidate.score)}</span></div>
        <p className="text-muted-foreground">{candidate.reason}</p>
        <details>
          <summary className="cursor-pointer text-xs font-medium text-indigo-700">Score details</summary>
          <dl className="mt-1 space-y-1 text-xs">
            {Object.entries(candidate.components).map(([key, score]) => <div key={key} className="grid grid-cols-[1fr_1fr_auto] items-center gap-2">
              <dt className="capitalize">{key.replaceAll('_', ' ')}</dt>
              <dd><progress value={Math.max(0, Math.min(1, score))} max={1} aria-label={key} className="h-1.5 w-full accent-indigo-600" /></dd>
              <dd className="tabular-nums">{pct(score)}</dd>
            </div>)}
          </dl>
        </details>
      </li>)}
    </ol>
  </section>
}
