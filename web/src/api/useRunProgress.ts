import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Schemas } from './client'
import { queryKeys } from './hooks'
import { subscribeRun, terminalTypes } from './sse'
import { initialProgress, runReducer } from '@/lib/runReducer'

const pacingMs = 200

export function useRunProgress(id: number, pace: boolean) {
  const queryClient = useQueryClient()
  const [progress, dispatch] = useReducer(runReducer, initialProgress)
  const [connection, setConnection] = useState<'connected' | 'retrying' | 'closed'>('connected')
  const [revision, setRevision] = useState(0)
  const cursor = useRef(0)
  const ready = useRef(false)
  const resume = useCallback(() => { ready.current = true; setRevision(value => value + 1) }, [])

  useEffect(() => {
    const queue: Schemas['RunEvent'][] = []
    let timer: ReturnType<typeof setTimeout> | undefined
    let lastTransition = -Infinity
    const animate = pace || ready.current
    const invalidateRun = () => void queryClient.invalidateQueries({ queryKey: queryKeys.run(id) })

    function drain() {
      timer = undefined
      while (queue.length) {
        const event = queue[0]
        const transition = event.type === 'stage.started' || event.type === 'stage.completed'
        const wait = lastTransition + pacingMs - performance.now()
        if (animate && transition && wait > 0) {
          timer = setTimeout(drain, wait)
          return
        }
        queue.shift()
        if (transition) lastTransition = performance.now()
        cursor.current = event.seq
        dispatch(event)
        if (event.type === 'review.recorded' || event.type === 'decision.made' ||
          (event.type === 'stage.completed' && (event.stage === 'extract_fields' || event.stage === 'match_lines'))) invalidateRun()
        if (terminalTypes.has(event.type)) {
          invalidateRun()
          for (const key of [queryKeys.runs, queryKeys.inbox, queryKeys.stats, queryKeys.queue, queryKeys.orders]) {
            void queryClient.invalidateQueries({ queryKey: key })
          }
        }
      }
    }

    const stop = subscribeRun(id, cursor.current, event => {
      queue.push(event)
      if (timer === undefined) drain()
    }, setConnection)
    return () => { stop(); clearTimeout(timer) }
  }, [id, pace, queryClient, revision])

  return { progress, connection, resume, animate: pace || revision > 0 }
}
