import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { api, ApiError, type Schemas } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { ErrorState } from '@/components/EmptyState'
import { PageActions } from '@/components/layout/PageActions'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { inr, pct } from '@/lib/format'
import { reasons } from '@/lib/labels'
import { policyGroup, policyGroups, settingNames, validPolicyValue } from '@/lib/policySettings'
import { cn } from '@/lib/utils'

type PolicyResponse = Schemas['PolicyResponse']
type PreviewChange = Schemas['PolicyPreviewChange']
const shortOutcome = { APPROVE: 'Approve', HOLD: 'Hold', RETURN: 'Return', REJECT: 'Reject' }

function formatSetting(name: string, value: unknown) {
  if (value == null) return '—'
  const kind = settingNames[name]?.[1]
  if (kind === 'money') return inr(String(value))
  if (kind === 'percent') return pct(Number(value) / 100)
  if (kind === 'score') return pct(Number(value))
  if (kind === 'days') return String(value) + (Number(value) === 1 ? ' day' : ' days')
  if (typeof value === 'boolean') return value ? 'On' : 'Off'
  return String(value)
}

export function PolicyPreview({ policy }: { policy: PolicyResponse }) {
  const [editing, setEditing] = useState(false)
  const [section, setSection] = useState<string>(policyGroups[0].key)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [saveUnavailable, setSaveUnavailable] = useState(false)
  const cache = useQueryClient()
  const canSave = useQuery({
    queryKey: ['policy-can-save'], queryFn: ({ signal }) => api.policyCanSave(signal), enabled: editing, retry: false, staleTime: 60_000,
  })
  const preview = useMutation({ mutationFn: api.previewPolicy })
  const save = useMutation({
    mutationFn: api.updatePolicy,
    onSuccess: ({ version }) => {
      toast.success('Policy version ' + version + ' saved')
      void cache.invalidateQueries({ queryKey: queryKeys.policy })
      setEditing(false)
      setDraft({})
      preview.reset()
    },
    onError: error => { if (error instanceof ApiError && [404, 405, 501].includes(error.status)) setSaveUnavailable(true) },
  })
  const pending = preview.isPending || save.isPending
  const editable = canSave.data === true && !saveUnavailable
  const overrides: Record<string, Record<string, string | boolean>> = {}
  let valid = true
  for (const { key } of policyGroups) {
    for (const [name, value] of Object.entries(policyGroup(policy.policy, key))) {
      const data = draft[name]?.trim()
      const kind = settingNames[name]?.[1]
      if (data === undefined || !kind || data === String(value)) continue
      if (!validPolicyValue(kind, data)) { valid = false; continue }
      const group = (overrides[key] ??= {})
      group[name] = kind === 'boolean' ? data === 'true' : data
    }
  }
  const dirty = Object.keys(overrides).length > 0

  function runPreview(event: FormEvent) {
    event.preventDefault()
    if (valid && dirty && !pending) preview.mutate({ overrides, limit: 50 })
  }
  function setValue(name: string, value: string) {
    preview.reset()
    setDraft(data => ({ ...data, [name]: value }))
  }
  function closeEdit() {
    setEditing(false)
    setDraft({})
    preview.reset()
    save.reset()
  }

  return <div className="page-padding h-full min-h-0">
    <PageActions inlineWhenUnavailable>
      <span className="whitespace-nowrap text-meta text-muted-foreground">Version {policy.version}</span>
      {!editing && <Button type="button" size="sm" onClick={() => setEditing(true)}>Try policy changes</Button>}
    </PageActions>
    <div className="grid min-h-full gap-px border bg-border lg:h-full lg:min-h-0 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav aria-label="Policy sections" className="min-w-0 overflow-auto bg-card">
        <h2 className="panel-title hidden lg:flex">Policy sections</h2>
        <div className="flex gap-1 p-2 lg:grid">
          {policyGroups.map(group => <button key={group.key} type="button" aria-pressed={section === group.key}
            className={cn('min-h-8 shrink-0 rounded-sm px-2 text-left text-body text-muted-foreground hover:bg-muted', section === group.key && 'bg-accent font-medium text-primary hover:bg-accent')}
            onClick={() => { setSection(group.key); document.getElementById('policy-' + group.key)?.scrollIntoView?.({ block: 'start' }) }}>{group.label}</button>)}
        </div>
      </nav>
      <form className="relative min-h-0 min-w-0 overflow-auto bg-card" onSubmit={runPreview}>
        {editing && <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2 border-b bg-card p-2">
          <span className="mr-auto px-1 text-meta text-muted-foreground">Preview on up to 50 recent runs</span>
          <Button type="button" variant="ghost" size="sm" disabled={pending} onClick={closeEdit}>Cancel</Button>
          <Button type="submit" size="sm" disabled={!valid || !dirty || pending}>{preview.isPending ? 'Checking impact…' : 'Preview impact'}</Button>
          {editable && <Button type="button" variant="outline" size="sm" disabled={!valid || !dirty || !preview.isSuccess || pending}
            onClick={() => save.mutate({ overrides })}>{save.isPending ? 'Saving…' : 'Save policy'}</Button>}
        </div>}
        {editing && !canSave.isPending && !editable && <p className="border-b px-3 py-2 text-meta text-muted-foreground">Policy changes are applied by editing the policy file in this build.</p>}
        {!valid && <p role="alert" className="border-b px-3 py-2 text-meta text-reject">Enter a valid value for each changed setting. Percentages must be at most 100.</p>}
        {preview.isError && <ErrorState title="Could not preview the policy impact" error={preview.error} retry={() => preview.mutate({ overrides, limit: 50 })} />}
        {save.isError && !saveUnavailable && <ErrorState title="Could not save the policy" error={save.error} />}
        {preview.data && <section className="border-b" aria-live="polite">
          <header className="panel-title"><h2>Preview results</h2>
            <span className="text-meta font-normal text-muted-foreground">{preview.data.changed.length} changed · {preview.data.unchanged} unchanged</span>
          </header>
          {preview.data.changed.length ? <div className="overflow-auto"><table aria-label="Policy impact" className="w-full min-w-[520px] table-fixed">
            <colgroup><col className="w-[90px]" /><col className="w-[270px]" /><col /></colgroup>
            <thead className="table-head"><tr>{['Run', 'Decision change', 'Reasons changed'].map(title => <th key={title} scope="col" className="px-2.5 font-medium">{title}</th>)}</tr></thead>
            <tbody>{preview.data.changed.map(change => <PolicyChange key={change.run_id} change={change} />)}</tbody>
          </table></div> : <p className="px-3 py-2 text-meta text-muted-foreground">No outcomes changed for this set of runs.</p>}
        </section>}
        {policyGroups.map(group => {
          const values = Object.entries(policyGroup(policy.policy, group.key))
          return <section key={group.key} id={'policy-' + group.key} className={cn('scroll-mt-1 border-b last:border-b-0', editing && 'scroll-mt-12')}>
            <div className="border-b bg-muted px-3 py-2">
              <h2 className="text-section">{group.label}</h2>
              <p className="text-meta text-muted-foreground">{group.description}</p>
            </div>
            {values.length ? <dl className="divide-y px-3">
              {values.map(([name, value]) => {
                const label = settingNames[name]?.[0] ?? name.replaceAll('_', ' ')
                const kind = settingNames[name]?.[1]
                const control = 'policy-field-' + name
                const writable = editing && !!kind && kind !== 'text' && value != null
                const current = draft[name] ?? String(value)
                return <div key={name} className="grid min-h-9 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-1">
                  <dt className="min-w-0 first-letter:uppercase">{writable ? <label htmlFor={control}>{label}</label> : label}</dt>
                  <dd className="text-right font-medium">
                    {writable && kind === 'boolean' ? <select className="h-7 min-w-20 rounded-sm border bg-card px-1 text-body" id={control}
                      disabled={pending} value={current} onChange={event => setValue(name, event.target.value)}>
                      <option value="true">On</option><option value="false">Off</option>
                    </select> : writable ? <Input className="h-7 w-28 bg-card text-right text-body" id={control} inputMode={kind === 'days' ? 'numeric' : 'decimal'}
                      value={current} disabled={pending} aria-invalid={!validPolicyValue(kind, current.trim()) || undefined}
                      onChange={event => setValue(name, event.target.value)} /> : formatSetting(name, value)}
                  </dd>
                </div>
              })}
            </dl> : <p className="px-3 py-2 text-meta text-muted-foreground">No settings available.</p>}
          </section>
        })}
      </form>
    </div>
  </div>
}

function PolicyChange({ change }: { change: PreviewChange }) {
  const removed = change.reasons_before.filter(code => !change.reasons_after.includes(code))
  const added = change.reasons_after.filter(code => !change.reasons_before.includes(code))
  return <tr className="table-row">
    <td className="identifier px-2.5"><Link to={'/runs/' + change.run_id} className="text-link">{change.display_id}</Link></td>
    <td className="px-2.5"><div role="group" aria-label={shortOutcome[change.before] + ' → ' + shortOutcome[change.after]} className="flex items-center gap-1.5">
      <OutcomeBadge outcome={change.before} /><ArrowRight aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" /><OutcomeBadge outcome={change.after} />
    </div></td>
    <td className="px-2.5 py-1 text-meta text-muted-foreground">
      {!!removed.length && <p><strong className="text-foreground">Removed</strong> · {removed.map(code => reasons[code]).join(', ')}</p>}
      {!!added.length && <p><strong className="text-foreground">Added</strong> · {added.map(code => reasons[code]).join(', ')}</p>}
      {!added.length && !removed.length && 'Recorded reasons stayed the same.'}
    </td>
  </tr>
}
