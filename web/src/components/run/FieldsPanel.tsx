import type { Schemas } from '@/api/client'
import { EmptyState } from '@/components/EmptyState'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { inr, istDate, maskedBank, pct } from '@/lib/format'
import { fieldGroups, type FieldKey } from '@/lib/invoiceFields'
import { cn } from '@/lib/utils'

const confidence = {
  high: ['High', 'H', 'bg-approve'], medium: ['Medium', 'M', 'bg-faint'], low: ['Low', 'L', 'bg-hold'],
} as const
const validators: Record<string, string> = {
  gstin_checksum: 'GSTIN checksum valid', arithmetic: 'Amounts add up', words_match: 'Total matches the amount in words', human_verified: 'Verified in review',
}
const ids = new Set<FieldKey>(['invoice_number', 'supplier_gstin', 'buyer_gstin', 'po_reference', 'bank_account_number', 'bank_ifsc'])

function formatted(name: FieldKey, value: string | null) {
  if (name === 'invoice_date' || name === 'due_date') return istDate(value)
  if (name === 'subtotal' || name === 'total' || name === 'round_off') return inr(value)
  if (name === 'bank_account_number') return maskedBank(value)
  return value ?? '—'
}

export function FieldsPanel({ extraction, onHighlight }: {
  extraction: Schemas['RunDetail']['extraction']; onHighlight: (key: FieldKey | null) => void
}) {
  if (!extraction) return <EmptyState title="No extracted fields yet">The invoice fields appear here after the document is read.</EmptyState>
  return <div className="space-y-3">
    {Object.entries(fieldGroups).map(([group, fields]) => <section key={group} className="panel">
      <h3 className="panel-title">{group}</h3>
      <div className="overflow-x-auto">
        <table aria-label={group + ' fields'} className="w-full min-w-[360px] table-fixed text-meta">
          <colgroup><col className="w-[22%]" /><col className="w-[29%]" /><col className="w-[20%]" /><col className="w-[12%]" /><col className="w-[17%]" /></colgroup>
          <thead className="table-head"><tr>
            {['Field', 'Value', 'Printed as', 'Conf.', 'Source'].map(label => <th key={label} scope="col" className="px-1.5 font-medium">{label}</th>)}
          </tr></thead>
          <tbody>{Object.entries(fields).map(([key, label]) => {
            const id = key as FieldKey, field = extraction[id]
            const [name, initial, tone] = confidence[field.level]
            const value = formatted(id, field.value)
            const raw = id === 'bank_account_number' ? maskedBank(field.raw) : field.raw
            const isGrounded = field.grounded === 'exact' || field.grounded === 'fuzzy'
            const source = isGrounded ? (extraction.doc_kind === 'scanned' ? 'OCR' : 'Text layer') : 'Model only'
            const detail = [isGrounded ? 'Found on the page' : 'Could not verify against text on the page',
              ...field.validators.map(validator => validators[validator] ?? validator), ...field.notes].join(' · ')
            const numeric = ['subtotal', 'total', 'round_off'].includes(id)
            return <tr key={id} className="table-row hover:bg-accent focus-visible:bg-accent" tabIndex={field.bbox.length > 0 ? 0 : undefined}
              onMouseEnter={() => onHighlight(id)} onMouseLeave={() => onHighlight(null)} onFocus={() => onHighlight(id)} onBlur={() => onHighlight(null)}>
              <th scope="row" className="px-1.5 text-left font-medium text-muted-foreground">{label}</th>
              <td className={cn('truncate px-1.5 font-medium', ids.has(id) && 'identifier', numeric && 'text-right')} title={value}>{value}</td>
              <td className="truncate px-1.5 text-muted-foreground" title={raw ?? undefined}>{raw && raw !== value ? raw : '—'}</td>
              <td className="px-1.5">{field.value != null && <Tooltip>
                <TooltipTrigger asChild><button type="button" aria-label={name + ' confidence, ' + pct(field.confidence)} className="inline-flex items-center gap-1">
                  <span aria-hidden="true" className={cn('inline-block size-2', tone)} />{initial}
                </button></TooltipTrigger><TooltipContent className="max-w-60">{name} confidence · {pct(field.confidence)} · {detail}</TooltipContent>
              </Tooltip>}</td>
              <td className="px-1.5 text-muted-foreground">{field.value != null ? source : '—'}</td>
            </tr>
          })}</tbody>
        </table>
      </div>
    </section>)}
    <section className="panel">
      <h3 className="panel-title">Line items</h3>
      <table className="w-full text-meta"><thead className="table-head"><tr>
        <th scope="col" className="px-2 font-medium">Description</th>{['Quantity', 'Unit price', 'Amount'].map(label => <th key={label} scope="col" className="px-2 text-right font-medium">{label}</th>)}
      </tr></thead><tbody>
        {extraction.line_items.map(line => <tr key={line.index} className="table-row">
          <td className="px-2">{line.description}</td><td className="px-2 text-right">{line.quantity ?? '—'} {line.uom}</td>
          <td className="px-2 text-right">{inr(line.unit_price)}</td><td className="px-2 text-right">{inr(line.amount)}</td>
        </tr>)}
      </tbody></table>
    </section>
    <section className="panel">
      <h3 className="panel-title">Other details</h3>
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 p-2 text-meta">
        <dt className="text-muted-foreground">Currency</dt><dd className="text-right">{extraction.currency}</dd>
        <dt className="text-muted-foreground">GST total</dt><dd className="text-right">{inr(extraction.tax.total_tax)}</dd>
        <dt className="text-muted-foreground">Other charges</dt><dd className="text-right">{inr(extraction.other_charges_total)}</dd>
      </dl>
      {!!extraction.annotations.length && <ul className="flex flex-wrap gap-1.5 border-t p-2 text-meta">
        {extraction.annotations.map(note => <li key={note} className="rounded-sm border bg-muted px-1.5 py-0.5"><q>{note}</q></li>)}
      </ul>}
    </section>
  </div>
}
