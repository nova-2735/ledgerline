import { render, screen } from '@testing-library/react'
import { LedgerBar } from '../LedgerBar'

it('shows the billed, received-unbilled and outstanding parts of the blanket PO', () => {
  render(<LedgerBar ordered="100" received="90" billed="60" />)
  const bar = screen.getByRole('img', { name: 'Billed 60 (60%), Received, unbilled 30 (30%), Not received 10 (10%)' })
  expect(Array.from(bar.children, segment => (segment as HTMLElement).style.width)).toEqual(['60%', '30%', '10%'])
})
