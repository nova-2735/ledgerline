import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { queryKeys } from '@/api/hooks'
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState'
import { PolicyPreview } from '@/components/PolicyPreview'

export function Policy() {
  const policy = useQuery({ queryKey: queryKeys.policy, queryFn: ({ signal }) => api.policy(signal) })
  if (policy.isPending) return <div className="page-padding"><div className="panel"><LoadingState label="Loading invoice policy" /></div></div>
  if (policy.isError) return <div className="page-padding"><ErrorState title="Could not load the policy" error={policy.error} retry={() => void policy.refetch()} /></div>
  if (!Object.keys(policy.data.policy).length) return <EmptyState title="No policy settings are available" />
  return <PolicyPreview key={policy.data.version} policy={policy.data} />
}
