import type { Schemas } from '@/api/client'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { inr, istDate, maskedBank } from '@/lib/format'

export function PostingTable({ posting }: { posting: Schemas['PostingPayload'] }) {
  return <section className="space-y-2 rounded-lg border">
    <h3 className="section-title px-3 pt-3">Posting preview</h3>
    <Table>
      <TableHeader className="bg-slate-50"><TableRow>{['GL account', 'Cost centre', 'Taxable', 'Tax'].map((label, i) =>
        <TableHead key={label} className={i >= 2 ? 'text-right' : undefined}>{label}</TableHead>)}</TableRow></TableHeader>
      <TableBody>{posting.lines.map(line => <TableRow key={`${line.po_number}-${line.po_line_no}`}>
        <TableCell title={line.description}>{line.gl_account}</TableCell><TableCell>{line.cost_center}</TableCell>
        <TableCell className="text-right tabular-nums">{inr(line.taxable_amount)}</TableCell>
        <TableCell className="text-right tabular-nums">{inr(line.tax_amount)}</TableCell>
      </TableRow>)}</TableBody>
    </Table>
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 px-3 pb-3 text-sm">
      <dt className="text-muted-foreground">Due</dt><dd>{istDate(posting.due_date)}</dd>
      <dt className="text-muted-foreground">Remit to</dt><dd>{[
        posting.remit_to.bank_name, maskedBank(posting.remit_to.account_number ?? posting.remit_to.bank_account_number),
        posting.remit_to.ifsc ?? posting.remit_to.bank_ifsc,
      ].filter(value => value && value !== '—').join(' · ') || '—'}</dd>
    </dl>
  </section>
}
