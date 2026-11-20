import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, CornerDownLeft, FileText, Search } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '@/api/client'
import { queryKeys, useInbox, useRuns } from '@/api/hooks'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { destinations, invokeShortcut, shortcutEntries, type Shortcut } from '@/lib/shortcuts'

type Props = { open: boolean; onOpenChange: (open: boolean) => void; onReset: () => void; onSidebar: () => void }

export function CommandPalette({ open, onOpenChange, onReset, onSidebar }: Props) {
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent showCloseButton={false} className="top-[min(28vh,220px)] translate-y-0 gap-0 p-0 sm:max-w-[580px]">
      <DialogTitle className="sr-only">Command palette</DialogTitle>
      <DialogDescription className="sr-only">Find a page, run or action.</DialogDescription>
      {open && <PaletteContents close={() => onOpenChange(false)} onReset={onReset} onSidebar={onSidebar} />}
    </DialogContent>
  </Dialog>
}

function PaletteContents({ close, onReset, onSidebar }: { close: () => void; onReset: () => void; onSidebar: () => void }) {
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const cache = useQueryClient()
  const runs = useRuns({ limit: 7, q: query }, false, !search.trim() || query === search.trim())
  const inbox = useInbox()
  const process = useMutation({
    mutationFn: (docId: string) => api.createDemoRun(docId),
    onSuccess: ({ run_id }) => {
      close()
      void cache.invalidateQueries({ queryKey: queryKeys.runs })
      void cache.invalidateQueries({ queryKey: queryKeys.inbox })
      void navigate(`/runs/${run_id}`)
    },
    onError: () => toast.error('Could not process invoice'),
  })

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 160)
    return () => clearTimeout(timer)
  }, [search])

  const matches = (text: string) => search.trim().toLowerCase().split(/\s+/).every(word => text.toLowerCase().includes(word))
  const go = (path: string) => { close(); void navigate(path) }
  const invoke = (id: Shortcut) => { close(); if (id === 'sidebar') onSidebar(); else invokeShortcut(id) }
  const current = pathname === '/' ? 'Dashboard' : pathname === '/runs' ? 'Runs' : pathname === '/inbox' ? 'Inbox' : pathname === '/queue' ? 'Queue' : pathname.startsWith('/runs/') ? 'Run view' : ''
  const contextual = shortcutEntries.filter(([id, { group }]) => group === current ||
    (group === 'Review' && (current === 'Run view' || current === 'Queue')) ||
    (group === 'Lists' && ['Runs', 'Inbox', 'Queue'].includes(current) && (id !== 'search' || current !== 'Queue')))

  return <Command label="Search commands" shouldFilter={false} loop>
    <CommandInput value={search} onValueChange={setSearch} placeholder="Search pages, runs and actions…" aria-label="Search commands" />
    <CommandList>
      <CommandEmpty className="p-4 text-muted-foreground">No matching commands.</CommandEmpty>
      <CommandGroup heading="Go to">{destinations.filter(({ label, key }) => matches(`${label} g ${key}`)).map(({ id, label, path }) =>
        <CommandItem key={id} value={`go-${id}`} onSelect={() => go(path)}>{label}<ShortcutHint className="ml-auto" id={id} /></CommandItem>)}</CommandGroup>
      <CommandGroup heading="Runs">{(query === search.trim() ? runs.data?.items : [])?.map(run =>
        <CommandItem key={run.id} value={`run-${run.id}`} onSelect={() => go(`/runs/${run.id}`)}>
          <FileText className="size-3.5 text-muted-foreground" aria-hidden="true" /><span className="identifier">{run.display_id}</span>
          <span className="truncate">{run.vendor_name ?? run.filename}</span><span className="identifier ml-auto truncate text-muted-foreground">{run.invoice_number}</span><Kbd>Enter</Kbd>
        </CommandItem>)}
        {search.trim() && <CommandItem value="search-all-runs" onSelect={() => go(`/runs?q=${encodeURIComponent(search.trim())}`)}><Search className="size-3.5" />Search all runs<Kbd className="ml-auto">Enter</Kbd></CommandItem>}
      </CommandGroup>
      <CommandGroup heading="Process demo invoice">{inbox.data?.filter(doc => matches(`${doc.doc_id} ${doc.title} ${doc.sender_name} ${doc.subject}`)).map(doc =>
        <CommandItem key={doc.doc_id} value={`process-${doc.doc_id}`} disabled={process.isPending} onSelect={() => process.mutate(doc.doc_id)}>
          <span className="identifier text-muted-foreground">{doc.doc_id}</span><span className="truncate">{doc.title}</span><Kbd className="ml-auto">Enter</Kbd>
        </CommandItem>)}</CommandGroup>
      <CommandGroup heading="Actions">
        {matches('Reset demo data') && <CommandItem value="reset" onSelect={() => { close(); onReset() }}>Reset demo data<Kbd className="ml-auto">Enter</Kbd></CommandItem>}
        {(['theme', 'sidebar', 'help'] as const).map(id => {
          const spec = shortcutEntries.find(([key]) => key === id)![1]
          return matches(spec.label) && <CommandItem key={id} value={id} onSelect={() => invoke(id)}>{spec.label}<ShortcutHint className="ml-auto" id={id} /></CommandItem>
        })}
      </CommandGroup>
      <CommandGroup heading="Current page">{contextual.filter(([, { label }]) => matches(label)).map(([id, { label }]) =>
        <CommandItem key={id} value={id} onSelect={() => invoke(id)}>{label}<ShortcutHint id={id} className="ml-auto" /></CommandItem>)}</CommandGroup>
    </CommandList>
    <div className="flex gap-4 border-t px-3 py-2 text-meta text-muted-foreground">
      <span className="flex items-center gap-1"><ArrowUp className="size-3" /><ArrowDown className="size-3" /> Navigate</span>
      <span className="flex items-center gap-1"><CornerDownLeft className="size-3" /> Select</span>
      <span className="ml-auto flex items-center gap-1"><Kbd>Esc</Kbd> Close</span>
    </div>
  </Command>
}
