import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { api, type InboxItem } from '@/api/client'
import { fixtures } from '@/mocks/fixtures'
import { Inbox } from '../Inbox'

afterEach(() => vi.restoreAllMocks())

it.each([false, true])('shows the optional stress folder only when populated (%s)', async stress => {
  const docs: InboxItem[] = fixtures.inbox.slice(0, 2).map((doc, index) => ({
    ...doc, processed_run_ids: [], ...(stress && index === 0 ? { group: 'stress' as const } : {}),
  }))
  vi.spyOn(api, 'demoInbox').mockResolvedValue(docs)
  vi.spyOn(api, 'listRuns').mockResolvedValue({ items: [], total: 0 })
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Inbox /></MemoryRouter></QueryClientProvider>)
  const list = screen.getByRole('region', { name: 'Messages' })
  await within(list).findByText(docs[1].subject)
  const folder = screen.queryByRole('button', { name: /Stress tests/ })
  if (!stress) expect(folder).toBeNull()
  else {
    fireEvent.click(folder!)
    expect(within(list).queryByText(docs[1].subject)).toBeNull()
    expect(within(list).getByText(docs[0].subject)).toBeTruthy()
  }
})
