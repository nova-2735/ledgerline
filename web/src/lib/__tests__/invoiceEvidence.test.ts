import { fixtures } from '@/mocks/fixtures'
import { invoiceEvidence } from '../invoiceFields'

it('opens the printed invoice line referenced by a failed match', () => {
  const run = fixtures.details.S01
  const box = { page: 2, x0: 0.1, y0: 0.3, x1: 0.8, y1: 0.4 }
  const line = { ...run.extraction!.line_items[0], index: 2, bbox: [box] }
  const extraction = { ...run.extraction!, line_items: [line] }
  const check = { ...run.checks[0], evidence: { invoice_line: 3 } }
  expect(invoiceEvidence(check, extraction)).toMatchObject({ id: 'line-3', bbox: [box] })
  expect(invoiceEvidence(check, null)).toBeNull()
})
