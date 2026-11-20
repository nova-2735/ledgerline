import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type Schemas } from '@/api/client'
import { queryKeys, useInbox } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { OutcomeBadge } from '@/components/OutcomeBadge'
import { Panel } from '@/components/Panel'
import { inr } from '@/lib/format'
import { stages } from '@/lib/labels'
import { policyGroup } from '@/lib/policySettings'
import { cn } from '@/lib/utils'

const checks: Record<Schemas['StageName'], string> = {
  intake: 'Check that the attachment is a readable, unlocked PDF within the upload limits. Keep the original file with its run.',
  read_document: 'Read each page and locate the printed words. Scanned pages can use optical character recognition.',
  extract_fields: 'Read the supplier, invoice number, dates, bank details and line items exactly as printed. Link the values to their places on the page.',
  validate_document: 'Check that this is an invoice. Check required fields, dates and whether line amounts add up to the total.',
  identify_vendor: 'Find the supplier in the vendor master. Check its status, tax registration and bank account before payment.',
  check_tax: 'Check the buyer and supplier tax numbers and whether the GST type, rate and amount fit the purchase.',
  resolve_po: 'Look up the purchase order. When its number is missing, compare likely orders and ask the buyer to confirm a proposed match.',
  match_lines: 'Compare quantities and prices with the order, receipts and amounts already billed. Flag goods that have yet to arrive.',
  check_duplicates: 'Search earlier invoices for the same file, invoice number or a similar bill from the supplier.',
  decide: 'Apply the recorded policy to all the checks. Produce one outcome and identify the person who can resolve an exception.',
  explain_route: 'Summarise the evidence, prepare the next question and send the case to its owner. Approved invoices receive posting lines.',
}
const entries = Object.entries(stages) as [Schemas['StageName'], string][]
const roles = [
  ['The model reads', 'It transcribes the printed invoice. You can inspect the original page alongside the fields.'],
  ['Rules decide', 'Checks compare those fields with purchasing records and policy. The rules set the outcome.'],
  ['The model explains', 'It can put the reasons into plain English. The run keeps the checks and policy version behind the explanation.'],
]
const owners: Record<Schemas['Outcome'], string> = {
  APPROVE: 'Accounts payable can use the posting lines to prepare payment.',
  HOLD: 'The named buyer, receiving, treasury or finance reviewer answers the question and records the evidence.',
  RETURN: 'Accounts payable asks the supplier to correct the invoice or send the missing information.',
  REJECT: 'Accounts payable keeps the decision on record and excludes the invoice from payment.',
}

export default function HowItWorks() {
  const [selected, select] = useState<Schemas['StageName']>('intake')
  const policy = useQuery({ queryKey: queryKeys.policy, queryFn: ({ signal }) => api.policy(signal) })
  const inbox = useInbox()
  const edge = inbox.data?.filter(item => item.is_edge_case)
  const values = policy.data?.policy ?? {}
  const limits = policyGroup(values, 'tolerances')
  const approval = policyGroup(values, 'approval')
  return <article className="page-padding space-y-4">
    <section aria-label="Who does what" className="grid gap-px border bg-border md:grid-cols-3">
      {roles.map(([title, description]) => <div key={title} className="bg-card p-3"><h2 className="text-section">{title}</h2><p className="mt-1 text-muted-foreground">{description}</p></div>)}
    </section>
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(330px,0.85fr)_minmax(0,1.25fr)]">
      <Panel title="From invoice to decision">
        <ol className="divide-y">{entries.map(([id, label], index) => <li key={id}>
          <button className={cn('flex min-h-9 w-full items-center gap-3 px-3 text-left hover:bg-muted', selected === id && 'bg-accent text-primary')} aria-expanded={selected === id} aria-controls={'guide-' + id} onClick={() => select(id)}>
            <span className="w-5 text-right text-meta">{index + 1}</span>{label}
          </button>
          <p id={'guide-' + id} hidden={selected !== id} className="border-l-2 border-primary py-2 pr-4 pl-10 text-muted-foreground">{checks[id]}</p>
        </li>)}</ol>
      </Panel>
      <div className="space-y-4">
        <Panel title="Who acts on each outcome"><dl className="divide-y">{(Object.keys(owners) as Schemas['Outcome'][]).map(outcome =>
          <div key={outcome} className="grid grid-cols-[145px_1fr] gap-3 p-3"><dt><OutcomeBadge outcome={outcome} compact /></dt><dd>{owners[outcome]}</dd></div>)}</dl></Panel>
        <Panel title="Current policy" action={<Link className="text-link" to="/policy">Open policy</Link>}>
          {policy.isPending ? <LoadingState /> : policy.isError ? <ErrorState title="Could not load policy" retry={() => void policy.refetch()} /> :
            <ul className="list-disc space-y-1 py-3 pr-4 pl-8">
              <li>Unit prices may exceed the order price by up to {String(limits.unit_price_pct)}%.</li>
              <li>The invoice total may differ by up to {String(limits.header_pct)}% or {inr(String(limits.header_abs))}, whichever is lower.</li>
              <li>Invoices above {inr(String(approval.auto_approve_limit))} need a reviewer’s approval.</li>
            </ul>}
        </Panel>
        <Panel title="Try these">{inbox.isPending ? <LoadingState /> : inbox.isError ? <ErrorState title="Could not load example invoices" retry={() => void inbox.refetch()} /> :
          edge?.length ? <ul className="divide-y">{edge.map(doc => <li key={doc.doc_id}><Link className="flex gap-3 px-3 py-2 text-link" to={'/inbox?folder=edge&doc=' + encodeURIComponent(doc.doc_id)}><span className="identifier">{doc.doc_id}</span>{doc.title}</Link></li>)}</ul> :
          <EmptyState title="No edge cases in the inbox" />}</Panel>
      </div>
    </div>
  </article>
}
