import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Schemas } from './client'
import { queryKeys } from './hooks'
import { subscribeRun, terminalTypes } from './sse'
import { initialProgress, runReducer } from '@/lib/runReducer'

const pacingMs = 200

export function useRunProgress(id: number, pace: boolean, lastReviewAt?: string) {
  const queryClient = useQueryClient()
  const [progress, dispatch] = useReducer(runReducer, initialProgress)
  const [connection, setConnection] = useState<'connected' | 'retrying' | 'closed'>('connected')
  const [revision, setRevision] = useState(0)
  const cursor = useRef(0)
  const ready = useRef(false)
  const reviewAt = useRef(lastReviewAt ? Date.parse(lastReviewAt) : -Infinity)
  const resume = useCallback((reviewedAt?: string) => {
    if (reviewedAt) reviewAt.current = Date.parse(reviewedAt)
    ready.current = true
    setRevision(value => value + 1)
  }, [])

  useEffect(() => {
    const queue: Schemas['RunEvent'][] = []
    let timer: ReturnType<typeof setTimeout> | undefined
    let stop: (() => void) | undefined
    let lastTransition = -Infinity
    const animate = pace || ready.current
    const invalidateRun = () => void queryClient.invalidateQueries({ queryKey: queryKeys.run(id) })

    function drain() {
      timer = undefined
      while (queue.length) {
        const event = queue[0]
        const transition = event.type === 'stage.started' || event.type === 'stage.completed'
        const historical = Date.parse(event.ts) < reviewAt.current
        const wait = lastTransition + pacingMs - performance.now()
        if (animate && transition && !historical && wait > 0) {
          timer = setTimeout(drain, wait)
          return
        }
        queue.shift()
        if (transition && !historical) lastTransition = performance.now()
        cursor.current = event.seq
        dispatch(event)
        if (historical) continue
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

    function connect(after: number) {
      let latest: Schemas['RunEvent'] | undefined
      stop = subscribeRun(id, after, event => {
        latest = event
        queue.push(event)
        if (timer === undefined) drain()
      }, state => {
        // A saved review can follow an earlier terminal event in the same run.
        if (state === 'closed' && latest && terminalTypes.has(latest.type) && Date.parse(latest.ts) < reviewAt.current) {
          connect(latest.seq)
        } else setConnection(state)
      })
    }
    connect(cursor.current)
    return () => { stop?.(); clearTimeout(timer) }
  }, [id, pace, queryClient, revision])

  return { progress, connection, resume, animate: pace || revision > 0 }
}
