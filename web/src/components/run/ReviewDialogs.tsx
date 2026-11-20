import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Schemas } from '@/api/client'
import { ErrorState } from '@/components/EmptyState'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { inr } from '@/lib/format'
import { criticalFields, fieldLabels } from '@/lib/invoiceFields'
import { actions } from '@/lib/labels'
import { approvalBlock } from './DecisionPanel'

type Run = Schemas['RunDetail']
type Action = Schemas['ActionType']
type Review = Schemas['ReviewRequest']
let recentReviewer = ''

const descriptions: Record<Action, string> = {
  confirm_po: 'Select the purchase order this invoice belongs to.',
  verify_bank: 'Use a trusted number from the vendor record and document your verification.',
  correct_fields: 'Check these values against the original invoice and correct any differences.',
  not_duplicate: 'Record how you determined this invoice is distinct from the earlier invoice.',
  approve: 'Confirm that this invoice can be approved for payment.',
  reject: 'Confirm that this invoice should be rejected.',
  send_to_vendor: 'Record that you sent the request to the vendor.',
  reopen: 'Record why this invoice needs another review.',
}

export function ReviewDialogs({ action, run, onClose, onReviewed }: {
  action: Action | null; run: Run; onClose: () => void; onReviewed: (run: Run) => void
}) {
  if (!action) return null
  return <ReviewForm key={`${run.id}-${action}`} action={action} run={run} onClose={onClose} onReviewed={onReviewed} />
}

function ReviewForm({ action, run, onClose, onReviewed }: {
  action: Action; run: Run; onClose: () => void; onReviewed: (run: Run) => void
}) {
  const candidates = [...(run.matching?.po_candidates ?? [])].sort((a, b) => b.score - a.score)
  const [reviewer, setReviewer] = useState(recentReviewer)
  const [note, setNote] = useState('')
  const [po, setPo] = useState(candidates[0]?.po_number ?? run.po_number ?? '')
  const [verified, setVerified] = useState(false)
  const [called, setCalled] = useState(false)
  const [knownContact, setKnownContact] = useState(false)
  const [corrections, setCorrections] = useState<Record<string, string>>({})
  const lowConfidence = run.checks.some(check => check.code === 'FIELD_LOW_CONFIDENCE' && !check.resolved_by_review)
    || Boolean(run.decision?.reasons.includes('FIELD_LOW_CONFIDENCE'))
  const changed = Object.fromEntries(Object.entries(corrections).filter(([name, value]) =>
    value.trim() !== (run.extraction?.[name as (typeof criticalFields)[number]]?.value ?? ''),
  ).map(([name, value]) => [name, value.trim()]))
  const draft = run.decision?.explanation.vendor_message
  const blocked = action === 'approve' ? approvalBlock(run) : undefined
  const valid = Boolean(reviewer.trim() && note.trim() && !blocked
    && (action !== 'confirm_po' || po.trim())
    && (action !== 'verify_bank' || (called && knownContact))
    && (action !== 'correct_fields' || verified || Object.keys(changed).length))

  const submit = useMutation({
    mutationFn: (request: Review) => api.reviewRun(run.id, request),
    onSuccess: (result, request) => {
      recentReviewer = request.reviewer
      toast.success('Review recorded')
      onReviewed(result)
      onClose()
    },
  })

  function save(event: FormEvent) {
    event.preventDefault()
    if (!valid || submit.isPending) return
    const request: Review = { action, reviewer: reviewer.trim(), note: note.trim() }
    if (action === 'confirm_po') request.po_number = po.trim()
    if (action === 'correct_fields') request.field_corrections = changed
    if (action === 'correct_fields' || (action === 'confirm_po' && lowConfidence)) request.fields_verified = verified
    submit.mutate(request)
  }

  return <Dialog open onOpenChange={open => { if (!open && !submit.isPending) onClose() }}>
    <DialogContent className="max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{action === 'send_to_vendor' ? 'Mark vendor email as sent' : actions[action]}</DialogTitle>
        <DialogDescription>{descriptions[action]}</DialogDescription>
      </DialogHeader>
      <form onSubmit={save} className="space-y-3">
        {(action === 'approve' || action === 'reject') && <p className="rounded-lg bg-slate-50 p-2.5 text-sm">
          <strong>{run.invoice_number ?? run.display_id}</strong> · <span className="tabular-nums">{inr(run.total)}</span>
        </p>}
        {action === 'confirm_po' && <fieldset className="space-y-2">
          <legend className="mb-1.5 text-sm font-semibold">Purchase order</legend>
          {candidates.length ? candidates.map(candidate => <label className="flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-sm" key={candidate.po_number}>
            <input name="purchase-order" type="radio" value={candidate.po_number} checked={po === candidate.po_number}
              onChange={event => setPo(event.target.value)} className="mt-0.5 accent-indigo-600" />
            <span><strong>{candidate.po_number}</strong><span className="block text-xs text-muted-foreground">{candidate.reason}</span></span>
          </label>) : <Input aria-label="Purchase order number" required value={po} onChange={event => setPo(event.target.value)} />}
        </fieldset>}
        {action === 'verify_bank' && <fieldset className="space-y-2 rounded-lg border bg-slate-50 p-2.5">
          <legend className="text-sm font-semibold">Verification</legend>
          <label className="flex items-center gap-2 text-sm"><Checkbox checked={called} onCheckedChange={state => setCalled(state === true)} />Called the number on file</label>
          <label className="flex items-center gap-2 text-sm"><Checkbox checked={knownContact} onCheckedChange={state => setKnownContact(state === true)} />Spoke to a known contact</label>
        </fieldset>}
        {action === 'correct_fields' && <fieldset className="grid gap-2 sm:grid-cols-2">
          <legend className="mb-1.5 text-sm font-semibold">Invoice fields</legend>
          {criticalFields.map(field => <label key={field} className="grid gap-1 text-sm">
            {fieldLabels[field]}<Input value={corrections[field] ?? run.extraction?.[field].value ?? ''}
              onChange={event => setCorrections(values => ({ ...values, [field]: event.target.value }))} />
          </label>)}
        </fieldset>}
        {(action === 'correct_fields' || (action === 'confirm_po' && lowConfidence)) && <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={verified} onCheckedChange={state => setVerified(state === true)} />I’ve checked the highlighted fields
        </label>}
        {action === 'send_to_vendor' && draft && <div className="space-y-1 rounded-lg border bg-slate-50 p-2.5 text-sm">
          <p><strong>To</strong> {draft.to}</p><p><strong>Subject</strong> {draft.subject}</p>
          <p className="mt-2 whitespace-pre-wrap">{draft.body}</p>
        </div>}
        <label className="grid gap-1.5 text-sm font-medium">Reviewer name
          <Input required value={reviewer} onChange={event => setReviewer(event.target.value)} />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">Note
          <Textarea required value={note} onChange={event => setNote(event.target.value)} />
        </label>
        {blocked && <ErrorState title={blocked} />}
        {submit.isError && <ErrorState title="Could not record the review" error={submit.error} />}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={submit.isPending} onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={!valid || submit.isPending} variant={action === 'reject' ? 'destructive' : 'default'}>
            {submit.isPending ? 'Recording…' : 'Record review'}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
}
