import { api, ApiError, runEventsUrl, setAccessCode } from './client'

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    setAccessCode(null)
  })

  it('sends the access code header and query params', async () => {
    const fetchMock = mockFetch(200, { items: [], total: 0 })
    setAccessCode('letmein')
    const res = await api.listRuns({ outcome: 'HOLD', limit: 10 })
    expect(res.total).toBe(0)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/runs?outcome=HOLD&limit=10')
    expect((init.headers as Record<string, string>)['X-Access-Code']).toBe('letmein')
  })

  it('raises ApiError with the server code', async () => {
    mockFetch(501, { detail: 'not implemented', code: 'not_implemented' })
    await expect(api.stats()).rejects.toMatchObject({
      name: 'ApiError',
      status: 501,
      code: 'not_implemented',
    } satisfies Partial<ApiError>)
  })

  it('puts the access code in the SSE query string', () => {
    setAccessCode('abc')
    expect(runEventsUrl(7, 3)).toBe('/api/runs/7/events?after=3&code=abc')
  })
})
