import { render, screen } from '@testing-library/react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { fixtures } from '@/mocks/fixtures'
import { DecisionPanel } from '../DecisionPanel'

it('routes the bank change to Treasury and blocks approval without a vendor email', () => {
  const run = fixtures.details.S06
  render(<TooltipProvider><DecisionPanel run={run} onAction={vi.fn()} onHighlight={vi.fn()} /></TooltipProvider>)
  expect(screen.getByText('Treasury')).toBeTruthy()
  expect(screen.getAllByText(run.decision!.handoff!.question).length).toBeGreaterThan(0)
  expect((screen.getByRole<HTMLButtonElement>('button', { name: 'Approve' })).disabled).toBe(true)
  expect(screen.getByText('Possible payment-redirection attempt')).toBeTruthy()
  expect(screen.queryByRole('heading', { name: 'Vendor email draft' })).toBeNull()
})
