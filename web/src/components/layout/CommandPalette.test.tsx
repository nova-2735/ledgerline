import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { api } from '@/api/client'
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
})
