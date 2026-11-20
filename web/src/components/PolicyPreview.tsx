import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { api, ApiError, type Schemas } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { ErrorState } from '@/components/EmptyState'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { reasons } from '@/lib/labels'

type PolicyResponse = Schemas['PolicyResponse']
type PreviewChange = Schemas['PolicyPreviewChange']
const shortOutcome = { APPROVE: 'Approve', HOLD: 'Hold', RETURN: 'Return', REJECT: 'Reject' }
const controls = [
  { group: 'tolerances', name: 'unit_price_pct', label: 'Unit price tolerance (%)', max: 100 },
  { group: 'tolerances', name: 'header_abs', label: 'Maximum invoice total difference (₹)', max: Infinity },
  { group: 'approval', name: 'auto_approve_limit', label: 'Automatic approval limit (₹)', max: Infinity },
] as const

export function policyGroup(policy: Record<string, unknown>, key: string): Record<string, unknown> {
  const group = policy[key]
  return typeof group === 'object' && group !== null && !Array.isArray(group) ? group as Record<string, unknown> : {}
}

export function PolicyPreview({ policy, onClose }: { policy: PolicyResponse; onClose: () => void }) {
  const available = controls.flatMap(control => {
    const value = policyGroup(policy.policy, control.group)[control.name]
    return (typeof value === 'string' || typeof value === 'number') && Number.isFinite(Number(value))
      ? [{ ...control, value: String(value) }] : []
  })
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [saveUnavailable, setSaveUnavailable] = useState(false)
  const queryClient = useQueryClient()
  const canSave = useQuery({
    queryKey: ['policy-can-save'], queryFn: ({ signal }) => api.policyCanSave(signal), retry: false, staleTime: 60_000,
  })
  const preview = useMutation({ mutationFn: api.previewPolicy })
  const save = useMutation({
    mutationFn: api.updatePolicy,
    onSuccess: ({ version }) => {
      toast.success(`Policy version ${version} saved`)
      void queryClient.invalidateQueries({ queryKey: queryKeys.policy })
      onClose()
    },
    onError: error => {
      if (error instanceof ApiError && [404, 501].includes(error.status)) setSaveUnavailable(true)
    },
  })
  const editable = canSave.data && !saveUnavailable
  const pending = preview.isPending || save.isPending
  const valid = available.every(({ name, value, max }) => {
    const text = (draft[name] ?? value).trim()
    return /^\d+(\.\d{1,2})?$/.test(text) && Number.isFinite(Number(text)) && Number(text) <= max
  })
  const overrides: Record<string, Record<string, string>> = {}
  for (const { name, group, value } of available) {
    const changed = draft[name]?.trim()
    if (changed !== undefined && changed !== value) (overrides[group] ??= {})[name] = changed
  }
  const dirty = Object.keys(overrides).length > 0

  function runPreview(event: FormEvent) {
    event.preventDefault()
    if (!valid || !dirty || pending) return
    preview.mutate({ overrides, limit: 50 })
  }

  return <section className="panel space-y-4 p-4 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div>
        <h2 className="section-title">What-if preview</h2>
        <p className="mt-1 text-sm text-muted-foreground">See which decisions would change across up to 50 recent runs.</p>
      </div>
      <Button type="button" size="sm" variant="ghost" disabled={pending} onClick={onClose}>Close preview</Button>
    </div>
    <form onSubmit={runPreview} className="space-y-3">
      {available.length > 0 ? <fieldset className="grid gap-3 sm:grid-cols-3" disabled={pending}>
        {available.map(({ name, label, value }) => <label key={name} className="grid gap-1.5 text-sm font-medium">
          {label}<Input type="text" inputMode="decimal" value={draft[name] ?? value} onChange={event => {
            preview.reset()
            setDraft(values => ({ ...values, [name]: event.target.value }))
          }} />
        </label>)}
      </fieldset> : <p className="text-sm text-muted-foreground">There are no preview settings available for this policy.</p>}
      {!valid && <p role="alert" className="text-sm text-rose-800">Enter non-negative values with up to two decimal places. Percentages must be at most 100.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!valid || !dirty || pending}>{preview.isPending ? 'Checking impact…' : 'Preview impact'}</Button>
        {editable && <Button type="button" variant="outline" disabled={!valid || !dirty || !preview.isSuccess || pending}
          onClick={() => save.mutate({ overrides })}>{save.isPending ? 'Saving…' : 'Save policy'}</Button>}
      </div>
    </form>
    {!editable && <p className="text-sm text-muted-foreground">Policy changes are applied by editing the policy file in this build.</p>}
    {preview.isError && <ErrorState title="Could not preview the policy impact" error={preview.error}
      retry={() => preview.mutate({ overrides, limit: 50 })} />}
    {save.isError && !saveUnavailable && <ErrorState title="Could not save the policy" error={save.error} />}
    {preview.data && <section className="space-y-2 border-t pt-3" aria-live="polite">
      <h3 className="section-title">Preview results</h3>
      <p className="text-sm text-muted-foreground tabular-nums">
        {preview.data.changed.length} changed · {preview.data.unchanged} unchanged
      </p>
      {preview.data.changed.length ? <ul className="divide-y rounded-lg border">
        {preview.data.changed.map(change => <PolicyChange key={change.run_id} change={change} />)}
      </ul> : <p className="rounded-lg bg-slate-50 p-3 text-sm">No outcomes changed for this set of runs.</p>}
    </section>}
  </section>
}

function PolicyChange({ change }: { change: PreviewChange }) {
  const removed = change.reasons_before.filter(code => !change.reasons_after.includes(code))
  const added = change.reasons_after.filter(code => !change.reasons_before.includes(code))
  return <li className="space-y-2 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <Link to={`/runs/${change.run_id}`} className="font-medium text-indigo-700 hover:underline">{change.display_id}</Link>
      <div role="group" aria-label={`${shortOutcome[change.before]} → ${shortOutcome[change.after]}`} className="flex flex-wrap items-center gap-2">
        <OutcomeBadge outcome={change.before} /><ArrowRight aria-hidden="true" className="size-4 text-slate-500" /><OutcomeBadge outcome={change.after} />
      </div>
    </div>
    {removed.length > 0 && <p className="text-sm"><strong>Removed</strong> · {removed.map(code => reasons[code]).join(', ')}</p>}
    {added.length > 0 && <p className="text-sm"><strong>Added</strong> · {added.map(code => reasons[code]).join(', ')}</p>}
    {!added.length && !removed.length && <p className="text-sm text-muted-foreground">The recorded reasons stayed the same.</p>}
  </li>
}
