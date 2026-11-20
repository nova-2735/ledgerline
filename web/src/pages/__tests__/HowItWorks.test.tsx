import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '@/api/client'
import { fixtures } from '@/mocks/fixtures'
import HowItWorks from '../HowItWorks'

it('explains a selected stage, displays the active limit and links directly to example invoices', async () => {
  vi.spyOn(api, 'policy').mockResolvedValue({ ...fixtures.policy, policy: { tolerances: { unit_price_pct: 3, header_pct: 4, header_abs: 125 }, approval: { auto_approve_limit: 12345 } } })
  vi.spyOn(api, 'demoInbox').mockResolvedValue(fixtures.inbox)
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><HowItWorks /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(screen.getByRole('button', { name: /Identify vendor/ }))
  expect(screen.getByText(/Find the supplier in the vendor master/).hidden).toBe(false)
  expect(await screen.findByText(/12,345.00/)).toBeTruthy()
  expect(screen.getAllByRole('link').some(link => link.getAttribute('href')?.startsWith('/inbox?folder=edge&doc='))).toBe(true)
  vi.restoreAllMocks()
})
