import type { Schemas } from './client'

const connections: Stream[] = []
class Stream extends EventTarget {
  readonly url: string
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()
  constructor(url: string) {
    super()
    this.url = url
    connections.push(this)
  }
  receive(seq: number, type: Schemas['RunEvent']['type']) {
    this.dispatchEvent(new MessageEvent(type, { data: JSON.stringify({ seq, type, run_id: 42 }) }))
  }
}

it('reconnects from the latest sequence and stops after a terminal event', async () => {
  vi.stubEnv('VITE_USE_MOCKS', '0')
  vi.resetModules()
  vi.stubGlobal('EventSource', Stream)
  vi.useFakeTimers()
  try {
    const { setAccessCode } = await import('./client')
    const { subscribeRun } = await import('./sse')
    setAccessCode('demo code')
    const event = vi.fn()
    const stop = subscribeRun(42, 2, event)
    expect(connections[0].url).toBe('/api/runs/42/events?after=2&code=demo+code')
    connections[0].receive(3, 'run.started')
    connections[0].onerror?.()
    vi.advanceTimersByTime(500)
    expect(connections[1].url).toContain('after=3')
    connections[1].receive(3, 'run.started')
    connections[1].receive(4, 'run.completed')
    expect(event).toHaveBeenCalledTimes(2)
    expect(connections[1].close).toHaveBeenCalledOnce()
    vi.advanceTimersByTime(15000)
    expect(connections).toHaveLength(2)
    stop()
  } finally {
    connections.length = 0
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  }
})
