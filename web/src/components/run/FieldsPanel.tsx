import type { Schemas } from '@/api/client'
import { EmptyState } from '@/components/EmptyState'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { inr, istDate, maskedBank, pct } from '@/lib/format'
import { fieldGroups, type FieldKey } from '@/lib/invoiceFields'

const confidence = {
  high: ['High', 'bg-emerald-50 text-emerald-800'],
  medium: ['Medium', 'bg-slate-100 text-slate-700'],
  low: ['Low', 'bg-amber-50 text-amber-900'],
} as const
const validators: Record<string, string> = {
  gstin_checksum: 'GSTIN checksum valid', arithmetic: 'Amounts add up', words_match: 'Total matches the amount in words',
}

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
  return <div className="space-y-4">
    {Object.entries(fieldGroups).map(([group, fields]) => <section key={group} className="overflow-hidden rounded-lg border">
      <h3 className="bg-slate-50 px-3 py-2 text-sm font-semibold">{group}</h3>
      <dl className="divide-y">
        {Object.entries(fields).map(([key, label]) => {
          const id = key as FieldKey
          const field = extraction[id]
          const [name, tone] = confidence[field.level]
          const value = formatted(id, field.value)
          const raw = id === 'bank_account_number' ? maskedBank(field.raw) : field.raw
          const isGrounded = field.grounded === 'exact' || field.grounded === 'fuzzy'
          const source = isGrounded ? extraction.doc_kind === 'scanned' ? 'OCR' : 'Text layer' : 'Model only'
          const details = [
            isGrounded ? 'Found on the page' : 'Could not verify against text on the page',
            ...field.validators.map(name => validators[name] ?? name), ...field.notes,
          ].join(' · ')
          return <div key={id} className="grid grid-cols-[minmax(6rem,.8fr)_minmax(0,1fr)] items-start gap-2 px-3 py-2 text-sm hover:bg-indigo-50/50"
            onMouseEnter={() => onHighlight(id)} onMouseLeave={() => onHighlight(null)}
            onFocus={() => onHighlight(id)} onBlur={() => onHighlight(null)}>
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="min-w-0">
              <span className="block font-medium wrap-anywhere tabular-nums">{value}</span>
              {raw && raw !== value && <span className="block text-xs text-muted-foreground">Printed as {raw}</span>}
              {field.value !== null && <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                <Tooltip>
                  <TooltipTrigger asChild><button type="button" className={`status-chip cursor-help ${tone}`} aria-label={`${label} confidence ${name}, ${pct(field.confidence)}`}>{name}</button></TooltipTrigger>
                  <TooltipContent className="max-w-56">{details}</TooltipContent>
                </Tooltip>
                {source}
              </div>}
            </dd>
          </div>
        })}
      </dl>
    </section>)}
    <section className="rounded-lg border">
      <h3 className="px-3 py-2 text-sm font-semibold">Line items</h3>
      <Table>
        <TableHeader className="bg-slate-50"><TableRow><TableHead>Description</TableHead><TableHead className="text-right">Quantity</TableHead>
          <TableHead className="text-right">Unit price</TableHead><TableHead className="text-right">Amount</TableHead></TableRow></TableHeader>
        <TableBody>{extraction.line_items.map(line => <TableRow key={line.index}>
          <TableCell className="min-w-24 whitespace-normal">{line.description}</TableCell><TableCell className="text-right tabular-nums">{line.quantity ?? '—'} {line.uom}</TableCell>
          <TableCell className="text-right tabular-nums">{inr(line.unit_price)}</TableCell><TableCell className="text-right tabular-nums">{inr(line.amount)}</TableCell>
        </TableRow>)}</TableBody>
      </Table>
    </section>
    <section className="space-y-2 rounded-lg border p-3">
      <h3 className="text-sm font-semibold">Other details</h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Currency</dt><dd>{extraction.currency}</dd>
        <dt className="text-muted-foreground">GST total</dt><dd className="tabular-nums">{inr(extraction.tax.total_tax)}</dd>
        <dt className="text-muted-foreground">Other charges</dt><dd className="tabular-nums">{inr(extraction.other_charges_total)}</dd>
      </dl>
      {!!extraction.annotations.length && <ul className="flex flex-wrap gap-1.5">
        {extraction.annotations.map(note => <li key={note} className="rounded bg-slate-100 px-2 py-1 text-xs"><q>{note}</q></li>)}
      </ul>}
    </section>
  </div>
}
