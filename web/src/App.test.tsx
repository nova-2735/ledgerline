import { render, screen } from '@testing-library/react'
import { api } from '@/api/client'
import App from './App'

describe('App', () => {
  it('renders the product name', () => {
    vi.spyOn(api, 'health').mockImplementation(() => new Promise(() => {}))
    vi.spyOn(api, 'queue').mockImplementation(() => new Promise(() => {}))
    vi.spyOn(api, 'listRuns').mockImplementation(() => new Promise(() => {}))
    vi.spyOn(api, 'stats').mockImplementation(() => new Promise(() => {}))
    render(<App />)
    expect(screen.getByRole('link', { name: /Ledgerline/ })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeTruthy()
    vi.restoreAllMocks()
  })
})
