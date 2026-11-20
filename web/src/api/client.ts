import type { components, operations } from './types.gen'

export type Schemas = components['schemas']

type Query<Op extends keyof operations> = operations[Op]['parameters'] extends { query?: infer Q }
  ? NonNullable<Q>
  : never

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === '1'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: string

  constructor(status: number, code: string, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

let accessCode: string | null = null

/** Set (or clear) the demo access code sent as `X-Access-Code` on every request. */
export function setAccessCode(code: string | null): void {
  accessCode = code && code.trim() ? code.trim() : null
}

export function getAccessCode(): string | null {
  return accessCode
}

type QueryValue = string | number | boolean | null | undefined

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`
}

export interface RequestOptions {
  query?: Record<string, QueryValue>
  json?: unknown
  form?: FormData
  signal?: AbortSignal
}

export async function request<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  if (import.meta.env.VITE_USE_MOCKS === '1') {
    const { mockRequest } = await import('@/mocks/mockServer')
    options.signal?.throwIfAborted()
    return mockRequest(method, path, options) as T
  }
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (accessCode) headers['X-Access-Code'] = accessCode
  let body: BodyInit | undefined
  if (options.form) {
    body = options.form
  } else if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  }

  const res = await fetch(buildUrl(path, options.query), {
    method,
    headers,
    body,
    signal: options.signal,
  })

  if (!res.ok) {
    let code = 'http_error'
    let detail = res.statusText || `Request failed with status ${res.status}`
    try {
      const err = (await res.json()) as Partial<Schemas['ErrorResponse']>
      if (typeof err.code === 'string') code = err.code
      if (typeof err.detail === 'string') detail = err.detail
    } catch {
      // Non-JSON error body: keep the status text.
    }
    throw new ApiError(res.status, code, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const enc = encodeURIComponent

/** URL for the live event stream. EventSource can't set headers, so the code goes in the query. */
export function runEventsUrl(runId: number, after?: number): string {
  return buildUrl(`/runs/${runId}/events`, { after, code: accessCode })
}

export function runDocumentUrl(runId: number): string {
  return buildUrl(`/runs/${runId}/document`, { code: accessCode })
}

export function runPageUrl(runId: number, page: number, scale?: number): string {
  return buildUrl(`/runs/${runId}/pages/${page}.png`, { scale, code: accessCode })
}

export const api = {
  health: (signal?: AbortSignal) => request<Schemas['HealthResponse']>('GET', '/health', { signal }),

  createRun: (file: File, forceFresh = false) => {
    const form = new FormData()
    form.append('file', file)
    form.append('force_fresh', String(forceFresh))
    return request<Schemas['RunCreated']>('POST', '/runs', { form })
  },
  listRuns: (query: Query<'list_runs'> = {}, signal?: AbortSignal) =>
    request<Schemas['RunList']>('GET', '/runs', { query, signal }),
  getRun: (runId: number, signal?: AbortSignal) =>
    request<Schemas['RunDetail']>('GET', `/runs/${runId}`, { signal }),
  getRunAudit: (runId: number) => request<Schemas['AuditExport']>('GET', `/runs/${runId}/audit`),
  reviewRun: (runId: number, body: Schemas['ReviewRequest']) =>
    request<Schemas['RunDetail']>('POST', `/runs/${runId}/review`, { json: body }),

  demoInbox: (signal?: AbortSignal) =>
    request<Schemas['DemoInboxItem'][]>('GET', '/demo/inbox', { signal }),
  createDemoRun: (docId: string, forceFresh = false) =>
    request<Schemas['RunCreated']>('POST', `/demo/runs/${enc(docId)}`, {
      json: { force_fresh: forceFresh } satisfies Schemas['DemoRunRequest'],
    }),
  resetDemo: () => request<Schemas['ResetResponse']>('POST', '/demo/reset'),

  queue: (query: Query<'get_queue'> = {}, signal?: AbortSignal) =>
    request<Schemas['QueueResponse']>('GET', '/queue', { query, signal }),
  vendors: (signal?: AbortSignal) => request<Schemas['VendorOut'][]>('GET', '/vendors', { signal }),
  purchaseOrders: (query: Query<'list_purchase_orders'> = {}, signal?: AbortSignal) =>
    request<Schemas['PurchaseOrderOut'][]>('GET', '/purchase-orders', { query, signal }),
  purchaseOrder: (po: string, signal?: AbortSignal) =>
    request<Schemas['PurchaseOrderDetail']>('GET', `/purchase-orders/${enc(po)}`, { signal }),

  policy: (signal?: AbortSignal) => request<Schemas['PolicyResponse']>('GET', '/policy', { signal }),
  policyCanSave: async (signal?: AbortSignal) => {
    if (USE_MOCKS) return false
    try {
      const specUrl = API_BASE.replace(/\/api\/?$/, '') + '/openapi.json'
      const response = await fetch(specUrl, { signal, headers: { Accept: 'application/json' } })
      if (response.ok && response.headers.get('Content-Type')?.includes('application/json')) {
        const spec = await response.json() as { paths?: Record<string, { put?: unknown }> }
        if (spec.paths?.['/api/policy']) return Boolean(spec.paths['/api/policy'].put)
      }
    } catch (error) {
      if (signal?.aborted) throw error
    }
    const response = await fetch(buildUrl('/policy'), {
      method: 'OPTIONS', signal, headers: accessCode ? { 'X-Access-Code': accessCode } : undefined,
    })
    if ([404, 501].includes(response.status)) return false
    return (response.headers.get('Allow') ?? '').split(',').some(method => method.trim().toUpperCase() === 'PUT')
  },
  previewPolicy: (body: Schemas['PolicyPreviewRequest']) =>
    request<Schemas['PolicyPreviewResponse']>('POST', '/policy/preview', { json: body }),
  updatePolicy: (body: Schemas['PolicyUpdateRequest']) =>
    request<Schemas['PolicyVersionResponse']>('PUT', '/policy', { json: body }),

  stats: (query: Query<'get_stats'> = {}, signal?: AbortSignal) =>
    request<Schemas['StatsResponse']>('GET', '/stats', { query, signal }),
}
