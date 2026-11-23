import { api, ApiError, auditPdfUrl, resetSummary, runEventsUrl, setAccessCode, waitText, withRateLimitRetry } from './client'

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('api client', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_USE_MOCKS', '0')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
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

  it('builds the audit PDF link with the access code for downloads', () => {
    setAccessCode('a & b')
    expect(auditPdfUrl(9)).toBe('/api/runs/9/audit.pdf?code=a+%26+b')
  })

  it('turns rate limits into friendly messages with the Retry-After wait', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: 'Too many invoices were sent from this address.', code: 'rate_limited' }),
      { status: 429, headers: { 'Retry-After': '12' } },
    )))
    const error = await api.createDemoRun('S01').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 429, code: 'rate_limited', retryAfter: 12 })
    expect((error as ApiError).message).toBe('Too many invoices were sent in a short time. Try again in 12 seconds.')
  })

  it('explains the live reading limit and how long to wait', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: 'This address has used its readings.', code: 'reading_limit' }),
      { status: 429, headers: { 'Retry-After': '1500' } },
    )))
    const error = await api.createDemoRun('U01', true).catch((e: unknown) => e) as ApiError
    expect(error.code).toBe('reading_limit')
    expect(error.message).toContain('read before still work')
    expect(error.message).toContain('about 25 minutes')
    expect(waitText(null)).toBe('a little while')
    expect(waitText(1)).toBe('1 second')
  })

  it('waits out a rate limit and tries again, but not a reading limit', async () => {
    const sleep = vi.fn(async () => {})
    const limited = new ApiError(429, 'rate_limited', 'slow down', 7)
    const fn = vi.fn().mockRejectedValueOnce(limited).mockResolvedValueOnce({ run_id: 5 })
    await expect(withRateLimitRetry(fn, { sleep })).resolves.toEqual({ run_id: 5 })
    expect(sleep).toHaveBeenCalledWith(7000)
    const budget = vi.fn().mockRejectedValue(new ApiError(429, 'reading_limit', 'used up', 900))
    await expect(withRateLimitRetry(budget, { sleep })).rejects.toMatchObject({ code: 'reading_limit' })
    expect(budget).toHaveBeenCalledTimes(1)
  })

  it('summarises a reset with its duration and mode', () => {
    expect(resetSummary({ status: 'ok', runs: 24, mode: 'snapshot', duration_ms: 412 })).toEqual({
      title: 'Demo data reset in 0.4 s', description: 'Restored the seeded history (24 runs).',
    })
    expect(resetSummary({ status: 'ok', runs: 24, mode: 'reseed', duration_ms: 79400 }).title).toBe('Demo data reset in 79 s')
  })

  it('puts the access code in the SSE query string', () => {
    setAccessCode('abc')
    expect(runEventsUrl(7, 3)).toBe('/api/runs/7/events?after=3&code=abc')
  })
})
