import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export type Folder = { id: string; label: string; count: number; age?: string; marker?: ReactNode }

export function WorkFolders({ title, folders, active, select }: { title: string; folders: Folder[]; active: string; select: (id: string) => void }) {
  return <nav className="min-h-0 min-w-0 overflow-auto bg-card" aria-label={title}>
    <h2 className="panel-title hidden lg:flex">{title}</h2>
    <div className="flex gap-1 p-2 lg:grid">
      {folders.map(folder => <button key={folder.id} type="button" aria-pressed={active === folder.id} onClick={() => select(folder.id)}
        className={cn('flex min-h-8 min-w-0 shrink-0 items-center gap-2 rounded-sm px-2 text-left text-body whitespace-nowrap text-muted-foreground hover:bg-muted hover:text-foreground', active === folder.id && 'bg-accent font-medium text-primary hover:bg-accent hover:text-primary')}>
        {folder.marker}<span className="truncate">{folder.label}</span>
        <span className="ml-auto flex items-center gap-1">
          {folder.age && <span className="text-meta font-normal text-muted-foreground" title="Oldest invoice">{folder.age}</span>}
          <span className="rounded-sm border px-1 text-meta font-medium">{folder.count}</span>
        </span>
      </button>)}
    </div>
  </nav>
}
