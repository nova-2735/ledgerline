import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { api } from '@/api/client'
import { fixtures } from '@/mocks/fixtures'
import { CommandPalette } from './CommandPalette'

function Path() {
  return <output>{useLocation().pathname}</output>
}

describe('command palette', () => {
  it('searches the runs API and navigates to a selected destination', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    const scroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView')
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
    const list = vi.spyOn(api, 'listRuns').mockResolvedValue({ items: [], total: 0 })
    vi.spyOn(api, 'demoInbox').mockResolvedValue([])
    const onOpenChange = vi.fn()
    try {
      render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
        <CommandPalette open onOpenChange={onOpenChange} onReset={vi.fn()} onSidebar={vi.fn()} />
        <Path />
      </MemoryRouter></QueryClientProvider>)
      const search = screen.getByRole('combobox', { name: 'Search commands' })
      fireEvent.change(search, { target: { value: 'SPI/26' } })
      await waitFor(() => expect(list).toHaveBeenCalledWith({ limit: 7, q: 'SPI/26' }, expect.anything()))
      fireEvent.change(search, { target: { value: 'Vendors' } })
      fireEvent.click(screen.getByRole('option', { name: 'Vendors' }))
      expect(onOpenChange).toHaveBeenCalledWith(false)
      expect(screen.getByText('/vendors')).toBeTruthy()
    } finally {
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
      if (scroll) Object.defineProperty(Element.prototype, 'scrollIntoView', scroll)
    }
  })

  it('opens the matching run when Enter is pressed after typing its ID', async () => {
    // Regression: run results arrived after "Search all runs" was auto-selected, so Enter
    // opened the filtered run list instead of the run shown first.
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    const scroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView')
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
    const run = fixtures.runs.items[0]
    vi.spyOn(api, 'listRuns').mockImplementation(async query => query?.q ? { items: [run], total: 1 } : { items: [], total: 0 })
    vi.spyOn(api, 'demoInbox').mockResolvedValue([])
    try {
      render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
        <CommandPalette open onOpenChange={vi.fn()} onReset={vi.fn()} onSidebar={vi.fn()} />
        <Path />
      </MemoryRouter></QueryClientProvider>)
      const search = screen.getByRole('combobox', { name: 'Search commands' })
      fireEvent.change(search, { target: { value: run.display_id } })
      const option = await screen.findByRole('option', { name: new RegExp(run.display_id) })
      await waitFor(() => expect(option.getAttribute('aria-selected')).toBe('true'))
      fireEvent.keyDown(search, { key: 'Enter' })
      expect(screen.getByText(`/runs/${run.id}`)).toBeTruthy()
    } finally {
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
      if (scroll) Object.defineProperty(Element.prototype, 'scrollIntoView', scroll)
    }
  })
})
