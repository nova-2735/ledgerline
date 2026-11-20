import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, ApiError } from './client'

export const queryKeys = {
  health: ['health'] as const,
  stats: ['stats'] as const,
  runs: ['runs'] as const,
  run: (id: number) => ['run', id] as const,
  inbox: ['inbox'] as const,
  queue: ['queue'] as const,
  vendors: ['vendors'] as const,
  orders: ['purchase-orders'] as const,
  policy: ['policy'] as const,
}

export function isAccessError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403)
}

export const useHealth = () => useQuery({
  queryKey: queryKeys.health,
  queryFn: async ({ signal }) => {
    const start = performance.now()
    const health = await api.health(signal)
    return { health, ms: Math.round(performance.now() - start) }
  },
  refetchInterval: 30_000,
  staleTime: 30_000,
})

export const useStats = (refresh = false) => useQuery({
  queryKey: queryKeys.stats,
  queryFn: ({ signal }) => api.stats({ days: 30 }, signal),
  refetchInterval: refresh ? 10_000 : false,
})

export const useRuns = (query: Parameters<typeof api.listRuns>[0] = {}, refresh = false, enabled = true) => useQuery({
  queryKey: [...queryKeys.runs, query],
  queryFn: ({ signal }) => api.listRuns(query, signal),
  refetchInterval: entry => refresh || entry.state.data?.items.some(run => run.status === 'running') ? 10_000 : false,
  placeholderData: keepPreviousData,
  enabled,
})

export const useInbox = () => useQuery({
  queryKey: queryKeys.inbox,
  queryFn: ({ signal }) => api.demoInbox(signal),
})

export const useRun = (id: number) => useQuery({
  queryKey: queryKeys.run(id),
  queryFn: ({ signal }) => api.getRun(id, signal),
  enabled: Number.isSafeInteger(id) && id > 0,
})

export const useQueue = (route?: NonNullable<Parameters<typeof api.queue>[0]>['route'], enabled = true) =>
  useQuery({
    queryKey: [...queryKeys.queue, route ?? 'all'],
    queryFn: ({ signal }) => api.queue(route ? { route } : {}, signal),
    enabled,
  })
