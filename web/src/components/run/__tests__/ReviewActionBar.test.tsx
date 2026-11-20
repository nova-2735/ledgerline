import { render, screen } from '@testing-library/react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { mockRunDocument, openMockScenario } from '@/mocks/mockServer'
import { ReviewActionBar } from '../ReviewActionBar'
import { approvalBlock } from '../reviewActions'

const vendorBlock = "Can't approve: Om Sai Traders isn't in the vendor master, so there's no vendor record to pay."

const button = (name: RegExp) => screen.getByRole<HTMLButtonElement>('button', { name })

function renderBar(blockingApproval?: string) {
  render(<TooltipProvider>
    <ReviewActionBar offered={['reject', 'approve']} blockingApproval={blockingApproval} onAction={() => {}} />
  </TooltipProvider>)
}

describe('Review action bar', () => {
  it('disables Approve and says why in plain view when the API would refuse it', () => {
    renderBar(vendorBlock)
    expect(button(/^Approve/).disabled).toBe(true)
    expect(screen.getByRole('note').textContent).toBe(`Approve is unavailable. ${vendorBlock}`)
    expect(button(/^Reject/).disabled).toBe(false)
  })

  it('leaves Approve enabled with no note when nothing blocks it', () => {
    renderBar()
    expect(button(/^Approve/).disabled).toBe(false)
    expect(screen.queryByRole('note')).toBeNull()
  })
})

describe('approvalBlock', () => {
  it('uses the reason the API sends with the run', () => {
    const id = openMockScenario('S11')
    const run = mockRunDocument(id)
    expect(run.approval_block).toMatch(/isn't in the vendor master/)
    expect(approvalBlock(run)).toBe(run.approval_block)
    expect(approvalBlock({ ...run, approval_block: null })).toBeUndefined()
  })
})
