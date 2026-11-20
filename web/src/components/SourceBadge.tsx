import { FilePlus2, FlaskConical, History, Mail } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { sources } from '@/lib/labels'

const icons = { upload: FilePlus2, demo: FlaskConical, seed: History, email: Mail }

export function SourceBadge({ source }: { source: Schemas['RunSource'] }) {
  const Icon = icons[source]
  return <span className="status-chip border bg-slate-50 text-slate-700"><Icon aria-hidden="true" />{sources[source]}</span>
}
