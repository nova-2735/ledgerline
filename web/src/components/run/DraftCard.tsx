import { Copy, Mail, StickyNote } from 'lucide-react'
import { toast } from 'sonner'
import type { Schemas } from '@/api/client'
import { Button } from '@/components/ui/button'

export function DraftCard({ draft, markAsSent }: { draft: Schemas['Message']; markAsSent?: () => void }) {
  const email = draft.channel === 'email'
  const Icon = email ? Mail : StickyNote
  async function copy() {
    try {
      await navigator.clipboard.writeText(`To: ${draft.to}\nSubject: ${draft.subject}\n\n${draft.body}`)
      toast.success('Draft copied')
    } catch {
      toast.error('Could not copy the draft')
    }
  }
  return <section className="space-y-2 rounded-sm border p-3">
    <h3 className="section-title flex items-center gap-2"><Icon aria-hidden="true" className="size-4 text-primary" />{email ? 'Vendor email draft' : 'Internal note'}</h3>
    <p className="text-xs font-medium text-muted-foreground">Draft — nothing is sent automatically</p>
    <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-sm">
      <dt className="text-muted-foreground">To</dt><dd className="wrap-anywhere">{draft.to}</dd>
      <dt className="text-muted-foreground">Subject</dt><dd>{draft.subject}</dd>
    </dl>
    <p className="rounded-md bg-muted p-2 text-sm whitespace-pre-wrap">{draft.body}</p>
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="outline" size="sm" onClick={() => void copy()}><Copy aria-hidden="true" />Copy</Button>
      {email && markAsSent && <Button type="button" size="sm" onClick={markAsSent}>Mark as sent</Button>}
    </div>
  </section>
}
