import { BookOpen, ClipboardList, FileStack, LayoutDashboard, List, ListChecks, Mail, PanelLeftClose, PanelLeftOpen, Search, SlidersHorizontal, Users } from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import { ShortcutHint } from '@/components/ShortcutHint'
import { destinations } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

const icons = { dashboard: LayoutDashboard, inbox: Mail, runs: List, queue: ListChecks, orders: ClipboardList, vendors: Users, policy: SlidersHorizontal, guide: BookOpen }

export function AppSidebar({ collapsed, count, toggle, openPalette, showSidebarShortcut }: { collapsed: boolean; count: number; toggle: () => void; openPalette: () => void; showSidebarShortcut: boolean }) {
  const CollapseIcon = collapsed ? PanelLeftOpen : PanelLeftClose
  return <aside className="flex min-h-0 flex-col border-r bg-card">
    <Link to="/" aria-label="Ledgerline" className={cn('flex h-12 shrink-0 items-center gap-2.5 px-3 text-section', collapsed && 'justify-center')}>
      <FileStack className="size-4 shrink-0 text-primary" aria-hidden="true" />{!collapsed && <span>Ledgerline</span>}
    </Link>
    <div className="px-2 pb-4">
      <button type="button" onClick={openPalette} title="Search and commands" aria-label={collapsed ? "Search and commands" : undefined} className={cn('flex h-8 w-full items-center gap-2 rounded-sm border bg-background px-2 text-meta text-muted-foreground hover:bg-muted', collapsed && 'justify-center px-0')}>
        <Search className="size-4 shrink-0" aria-hidden="true" />{!collapsed && <><span>Search…</span><ShortcutHint id="palette" className="ml-auto" /></>}
      </button>
    </div>
    <nav aria-label="Main navigation" className="space-y-4 px-2">
      {(['Workspace', 'Reference'] as const).map((section, index) => <div key={section}>
        {!collapsed && <div className="px-2 pb-1 text-meta font-medium text-muted-foreground">{section}</div>}
        {destinations.slice(index === 0 ? 0 : 4, index === 0 ? 4 : undefined).map(({ id, path, label }) => {
          const Icon = icons[id]
          return <NavLink key={id} to={path} end={id === 'dashboard'} title={label} aria-label={collapsed ? label : undefined}
            className={({ isActive }) => cn('relative flex h-[30px] items-center gap-2 rounded-sm px-2 text-body text-muted-foreground hover:bg-muted hover:text-foreground', collapsed && 'justify-center px-0', isActive && 'bg-accent font-medium text-primary hover:bg-accent hover:text-primary')}>
            <Icon className="size-4 shrink-0" aria-hidden="true" />
            {!collapsed && <span className="truncate">{label}</span>}
            {id === 'queue' && count > 0 && <span className={cn('rounded-sm bg-muted px-1 text-meta text-foreground', collapsed && 'absolute right-0 top-0 text-[9px]')}>{count}</span>}
            {!collapsed && <ShortcutHint className="ml-auto" id={id} />}
          </NavLink>
        })}
      </div>)}
    </nav>
    <button type="button" title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!collapsed} onClick={toggle}
      className={cn('mx-2 mt-auto mb-2 flex h-[30px] items-center gap-2 rounded-sm px-2 text-meta text-muted-foreground hover:bg-muted', collapsed && 'justify-center px-0')}>
      <CollapseIcon className="size-4" aria-hidden="true" />{!collapsed && <>Collapse sidebar{showSidebarShortcut && <ShortcutHint id="sidebar" className="ml-auto" />}</>}
    </button>
  </aside>
}
