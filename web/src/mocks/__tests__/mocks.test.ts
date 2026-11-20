import openapi from '../../../../backend/openapi.json'
import { fixtures } from '../fixtures'
import { mockRequest, replayMockEvents } from '../mockServer'

interface Schema {
  $ref?: string
  type?: string
  enum?: unknown[]
  anyOf?: Schema[]
  items?: Schema
  required?: string[]
  properties?: Record<string, Schema>
  additionalProperties?: Schema | boolean
}

const schema: Record<string, Schema> = openapi.components.schemas
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

function problems(value: unknown, spec: Schema, at: string): string[] {
  if (spec.$ref) return problems(value, schema[spec.$ref.split('/').at(-1)!], at)
  if (spec.anyOf) {
    return spec.anyOf.some(branch => problems(value, branch, at).length === 0)
      ? [] : spec.anyOf.flatMap(branch => problems(value, branch, at))
  }
  if (spec.enum && !spec.enum.includes(value)) return [`${at} has an invalid value`]
  if (spec.type === 'null') return value === null ? [] : [`${at} must be null`]
  if (spec.type === 'array') return Array.isArray(value)
    ? value.flatMap((item, index) => problems(item, spec.items ?? {}, `${at}[${index}]`)) : [`${at} must be an array`]
  if (spec.type === 'object') {
    if (!isObject(value)) return [`${at} must be an object`]
    const missing = (spec.required ?? []).filter(key => !Object.hasOwn(value, key)).map(key => `${at}.${key} is required`)
    return missing.concat(Object.entries(value).flatMap(([key, item]) => {
      const child = spec.properties?.[key] ?? spec.additionalProperties
      if (child === false) return [`${at}.${key} is unexpected`]
      return child && child !== true ? problems(item, child, `${at}.${key}`) : []
    }))
  }
  if (spec.type === 'integer') return Number.isInteger(value) ? [] : [`${at} must be an integer`]
  if (spec.type && typeof value !== spec.type) return [`${at} must be ${spec.type}`]
  return []
}

it('parses each fixture and matches its generated API schema', () => {
  const single = {
    HealthResponse: fixtures.health, StatsResponse: fixtures.stats, RunList: fixtures.runs,
    QueueResponse: fixtures.queue, PurchaseOrderDetail: fixtures.blanketOrder, PolicyResponse: fixtures.policy,
  }
  const lists = {
    DemoInboxItem: fixtures.inbox, VendorOut: fixtures.vendors, PurchaseOrderOut: fixtures.orders,
    RunDetail: Object.values(fixtures.details), RunEvent: Object.values(fixtures.events).flat(),
  }
  for (const [name, value] of Object.entries(single)) expect(problems(value, schema[name], name)).toEqual([])
  for (const [name, values] of Object.entries(lists)) {
    expect(values.flatMap((value, index) => problems(value, schema[name], `${name}[${index}]`))).toEqual([])
  }
})

it('uses strictly increasing, unique event sequences and a four-second extraction stage', () => {
  for (const events of Object.values(fixtures.events)) {
    expect(events.every((event, index) => index === 0 || event.seq > events[index - 1].seq)).toBe(true)
    const extraction = events.filter(event => event.stage === 'extract_fields')
    expect(Date.parse(extraction.at(-1)!.ts) - Date.parse(extraction[0].ts)).toBe(4000)
  }
})

it('creates an inbox run, resumes event replay after a cursor and returns the final detail', () => {
  vi.useFakeTimers()
  try {
    const { run_id } = mockRequest('POST', '/demo/runs/S04') as { run_id: number }
    expect(mockRequest('GET', `/runs/${run_id}`)).toMatchObject({ status: 'running', outcome: null })
    expect(mockRequest('GET', '/demo/inbox')).toContainEqual(expect.objectContaining({ doc_id: 'S04', processed_run_ids: [run_id] }))
    const received: number[] = []
    const end = vi.fn()
    replayMockEvents(run_id, 2, event => received.push(event.seq), end)
    vi.advanceTimersByTime(3000)
    expect(received[0]).toBe(3)
    expect(end).not.toHaveBeenCalled()
    vi.advanceTimersByTime(6000)
    expect(end).toHaveBeenCalledOnce()
    expect(mockRequest('GET', `/runs/${run_id}`)).toMatchObject({ status: 'awaiting_review', outcome: 'HOLD' })
  } finally {
    mockRequest('POST', '/demo/reset')
    vi.useRealTimers()
  }
})
