import { runEventsUrl, USE_MOCKS, type Schemas } from './client'

type Event = Schemas['RunEvent']
const types = [
  'run.created', 'run.started', 'stage.started', 'stage.log', 'stage.completed', 'decision.made',
  'run.awaiting_review', 'run.completed', 'run.failed', 'review.recorded', 'run.resumed',
] as const satisfies Event['type'][]
export const terminalTypes = new Set<Event['type']>(['run.completed', 'run.awaiting_review', 'run.failed'])

export function subscribeRun(
  id: number, after: number, onEvent: (event: Event) => void,
  onConnection?: (status: 'connected' | 'retrying' | 'closed') => void,
): () => void {
  let source: EventSource | undefined
  let retry: ReturnType<typeof setTimeout> | undefined
  let stopReplay: (() => void) | undefined
  let closed = false
  let cursor = after
  let delay = 500

  function close() {
    closed = true
    source?.close()
    clearTimeout(retry)
    stopReplay?.()
  }

  function receive(event: Event) {
    if (closed || event.run_id !== id || !Number.isSafeInteger(event.seq) || event.seq <= cursor) return
    cursor = event.seq
    delay = 500
    onEvent(event)
    if (terminalTypes.has(event.type)) {
      close()
      onConnection?.('closed')
    }
  }

  function connect() {
    if (closed) return
    source = new EventSource(runEventsUrl(id, cursor))
    source.onopen = () => onConnection?.('connected')
    source.onerror = () => {
      source?.close()
      if (closed) return
      onConnection?.('retrying')
      retry = setTimeout(connect, delay)
      delay = Math.min(delay * 2, 10_000)
    }
    for (const type of types) source.addEventListener(type, message => {
      try {
        const event = JSON.parse((message as MessageEvent<string>).data) as Event
        if (event.type === type) receive(event)
      } catch (error) {
        if (!(error instanceof SyntaxError)) throw error
      }
    })
  }

  if (USE_MOCKS) {
    void import('@/mocks/mockServer').then(({ replayMockEvents }) => {
      if (closed) return
      onConnection?.('connected')
      stopReplay = replayMockEvents(id, cursor, receive, () => {
        if (!closed) onConnection?.('closed')
      })
    })
  } else connect()

  return close
}
