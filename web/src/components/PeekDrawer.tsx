import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { runPageUrl, USE_MOCKS } from '@/api/client'
import { useRun } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { ErrorState, LoadingState } from '@/components/EmptyState'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { ShortcutHint } from '@/components/ShortcutHint'
import { inr } from '@/lib/format'
import { reasons } from '@/lib/labels'

export function PeekDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const run = useRun(id ?? 0)
  const image = useQuery({
    queryKey: ['peek-image', id],
    enabled: id != null && (run.data?.page_count ?? 0) > 0,
    queryFn: async () => USE_MOCKS ? (await import('@/mocks/mockDocument')).mockPageImage(id!, 1) : runPageUrl(id!, 1, 0.7),
    staleTime: Infinity,
  })
  return <Sheet open={id != null} onOpenChange={open => { if (!open) onClose() }}>
    <SheetContent className="w-full max-w-[420px] gap-0 overflow-y-auto sm:max-w-[420px]">
      <div className="border-b px-4 py-3">
        <SheetTitle className="identifier">{run.data?.display_id ?? 'Run preview'}</SheetTitle>
        <SheetDescription className="mt-1 truncate">{run.data?.vendor_name ?? 'Invoice run'}{run.data?.total ? ' · ' + inr(run.data.total) : ''}</SheetDescription>
      </div>
      {run.isPending ? <LoadingState label="Loading run preview" /> :
        run.isError ? <ErrorState title="Could not load run" error={run.error} retry={() => void run.refetch()} /> :
          <div className="space-y-4 p-4">
            <div className="panel space-y-2 p-3">
              <OutcomeBadge outcome={run.data.final_outcome ?? run.data.outcome} />
              <h2 className="text-title">{run.data.decision?.headline ?? 'Processing invoice'}</h2>
              {run.data.decision?.handoff?.question && <p>{run.data.decision.handoff.question}</p>}
            </div>
            {!!run.data.decision?.reasons.length && <ul className="list-inside list-disc space-y-1 text-muted-foreground">
              {run.data.decision.reasons.slice(0, 3).map(code => <li key={code}>{reasons[code]}</li>)}
            </ul>}
            {image.data && <img alt="First invoice page" src={image.data} className="mx-auto max-h-[58vh] w-full border bg-white object-contain" />}
          </div>}
      <div className="mt-auto border-t p-4">
        <Button autoFocus asChild><Link to={'/runs/' + id}>Open run <ShortcutHint id="open" /></Link></Button>
      </div>
    </SheetContent>
  </Sheet>
}
