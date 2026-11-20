import type { ReactNode } from 'react'
import { CircleAlert, Inbox } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from './ui/alert'
import { Button } from './ui/button'
import { Skeleton } from './ui/skeleton'

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="grid justify-items-center gap-2 px-6 py-12 text-center">
      <Inbox aria-hidden="true" className="mb-1 size-6 text-slate-400" />
      <h2 className="font-semibold">{title}</h2>
      {children && <div className="text-sm text-muted-foreground">{children}</div>}
    </div>
  )
}

export function LoadingState({ label = 'Loading' }: { label?: string }) {
  return <div role="status" className="space-y-3 p-5">
    <span className="sr-only">{label}</span>
    <Skeleton className="h-8 w-1/3" />
    <Skeleton className="h-9 w-full" />
    <Skeleton className="h-9 w-full" />
  </div>
}

export function ErrorState({ title, error, retry }: { title: string; error?: unknown; retry?: () => void }) {
  return <Alert variant="destructive">
    <CircleAlert aria-hidden="true" />
    <AlertTitle>{title}</AlertTitle>
    {error instanceof Error && <AlertDescription>{error.message}</AlertDescription>}
    {retry && <Button variant="outline" size="sm" className="col-start-2 mt-2 justify-self-start" onClick={retry}>Try again</Button>}
  </Alert>
}
