import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api } from '@/api/client'
import { fixtures } from '@/mocks/fixtures'
import { mockRequest } from '@/mocks/mockServer'
import { Policy } from '../Policy'

afterEach(() => {
  mockRequest('POST', '/demo/reset')
  vi.restoreAllMocks()
})

it('opens the S12 what-if preview from the read-only policy and shows what changed', async () => {
  const { run_id } = mockRequest('POST', '/demo/runs/S12') as { run_id: number }
  const now = Date.now()
  const time = vi.spyOn(Date, 'now').mockReturnValue(now + 10_000)
  try {
    vi.spyOn(api, 'policy').mockResolvedValue(fixtures.policy)
    vi.spyOn(api, 'policyCanSave').mockResolvedValue(false)
    const request = vi.spyOn(api, 'previewPolicy').mockImplementation(async body =>
      mockRequest('POST', '/policy/preview', { json: body }) as Awaited<ReturnType<typeof api.previewPolicy>>,
    )
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><Policy /></MemoryRouter>
    </QueryClientProvider>)
    expect(await screen.findByText('Version v1')).toBeTruthy()
    expect(screen.queryByLabelText('Unit price tolerance (%)')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try policy changes' }))
    fireEvent.change(screen.getByLabelText('Unit price tolerance (%)'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('Maximum invoice total difference (₹)'), { target: { value: '5000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Preview impact' }))
    expect(await screen.findByRole('group', { name: 'Hold → Approve' })).toBeTruthy()
    expect(screen.getByText('1 changed · 24 unchanged')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'R-0025' }).getAttribute('href')).toBe(`/runs/${run_id}`)
    expect(screen.getByText(/Unit price exceeds tolerance/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Save policy' })).toBeNull()
    expect(request).toHaveBeenCalledWith({
      limit: 50,
      overrides: { tolerances: { unit_price_pct: '10', header_abs: '5000' } },
    }, expect.anything())
    await waitFor(() => expect(mockRequest('GET', `/runs/${run_id}`)).toMatchObject({ outcome: 'HOLD' }))
  } finally {
    time.mockRestore()
  }
})
