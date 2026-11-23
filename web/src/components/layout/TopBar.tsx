import { ChevronRight } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { destinations } from '@/lib/shortcuts'

export function TopBar({ actionsRef }: { actionsRef: (element: HTMLDivElement | null) => void }) {
  const { pathname } = useLocation()
  const parent = destinations.find(item => item.path === pathname) ??
    destinations.find(item => item.path !== '/' && pathname.startsWith(item.path + '/'))
  const detail = parent && parent.path !== pathname ? decodeURIComponent(pathname.split('/').at(-1) ?? '') : null
  const record = parent?.id === 'runs' && detail && /^\d+$/.test(detail) ? 'R-' + detail.padStart(4, '0') : detail
  return <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b bg-card px-4 sm:px-6">
    <div className="flex min-w-0 shrink items-center gap-2 whitespace-nowrap">
      {record && parent ? <><Link className="text-body text-muted-foreground hover:text-foreground" to={parent.path}>{parent.label}</Link>
        <ChevronRight className="size-3 shrink-0 text-faint" aria-hidden="true" /><h1 title={record} className="identifier truncate">{record}</h1></> :
        <h1 title={parent?.label} className="truncate text-title">{parent?.label ?? 'Page not found'}</h1>}
    </div>
    <div ref={actionsRef} className="flex items-center gap-2" />
  </header>
}
