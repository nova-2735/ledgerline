import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { api } from '@/api/client'
import { Runs } from '@/pages/Runs'
import runs from '@/mocks/runs.json'
import type { Run } from '@/lib/runList'

function Location() { return <output aria-label="Current path">{useLocation().pathname}</output> }

describe('Runs table keyboard navigation', () => {
  it('moves the active row, selects it for export, and opens it', async () => {
    const items = runs.items.slice(0, 3) as Run[]
    vi.spyOn(api, 'listRuns').mockResolvedValue({ items, total: items.length })
    vi.spyOn(api, 'health').mockImplementation(() => new Promise(() => {}))
    try {
      render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/runs']}><Runs /><Location /></MemoryRouter></QueryClientProvider>)
      const table = await screen.findByRole('table', { name: 'Invoice runs' })
      const rows = within(table).getAllByRole('row').slice(1)
      fireEvent.keyDown(window, { key: 'j' })
      expect(rows[0].getAttribute('data-active')).toBe('true')
      fireEvent.keyDown(window, { key: 'j' })
      fireEvent.keyDown(window, { key: 'x' })
      expect(rows[1].getAttribute('data-active')).toBe('true')
      expect(within(rows[1]).getByRole<HTMLInputElement>('checkbox').checked).toBe(true)
      fireEvent.keyDown(window, { key: 'k' })
      const href = within(rows[0]).getAllByRole('link')[0].getAttribute('href')
      fireEvent.keyDown(window, { key: 'Enter' })
      await waitFor(() => expect(screen.getByLabelText('Current path').textContent).toBe(href))
    } finally { vi.restoreAllMocks() }
  })
})
