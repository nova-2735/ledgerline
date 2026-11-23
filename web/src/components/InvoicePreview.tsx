import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { runPageUrl, USE_MOCKS, type Schemas } from '@/api/client'
import { routes } from '@/lib/labels'
import { inr } from '@/lib/format'
import { effectiveOutcome } from '@/lib/runList'
import { OutcomeBadge } from './OutcomeBadge'

export function InvoicePreview({ run }: { run: Schemas['RunDetail'] }) {
  const image = useQuery({
    queryKey: ['peek-image', run.id], enabled: run.page_count > 0, staleTime: Infinity,
    queryFn: async () => USE_MOCKS ? (await import('@/mocks/mockDocument')).mockPageImage(run.id, 1) : runPageUrl(run.id, 1, 0.7),
  })
  const handoff = run.decision?.handoff
  return <section className="space-y-2 border-y py-3" aria-label="Last run decision">
    <div className="flex items-start gap-3">
      {image.data && <Link to={'/runs/' + run.id}><img className="h-24 w-[68px] shrink-0 border bg-white object-contain" alt={'Page 1 of ' + run.filename} src={image.data} /></Link>}
      <div className="min-w-0"><OutcomeBadge outcome={effectiveOutcome(run)} /><h4 className="mt-1 text-section">{run.decision?.headline ?? 'Awaiting a decision'}</h4>
        {handoff && <p className="mt-1 text-meta"><strong>{routes[handoff.owner]}</strong> · {handoff.question}</p>}</div>
    </div>
    <dl className="grid grid-cols-[70px_1fr] gap-x-3 gap-y-1 text-meta [&_dt]:text-muted-foreground">
      <dt>Amount</dt><dd>{inr(run.total)}</dd><dt>PO</dt><dd className="identifier">{run.po_number ?? '—'}</dd><dt>Vendor</dt><dd>{run.vendor_name ?? '—'}</dd>
    </dl>
  </section>
}
