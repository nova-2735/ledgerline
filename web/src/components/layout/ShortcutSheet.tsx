import { ShortcutHint } from '@/components/ShortcutHint'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { shortcutEntries, shortcutGroups } from '@/lib/shortcuts'

export function ShortcutSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="max-h-[85dvh] grid-rows-[auto_auto_minmax(0,1fr)] gap-2 sm:max-w-[680px]">
      <DialogTitle>Keyboard shortcuts</DialogTitle>
      <DialogDescription>Page shortcuts are active when you’re on that page.</DialogDescription>
      <div className="grid content-start gap-3 overflow-y-auto pt-2 sm:grid-cols-2">
        {shortcutGroups.map(group => <section key={group} className="min-w-0 border">
          <h3 className="border-b bg-muted px-2 py-1.5 text-section">{group}</h3>
          {shortcutEntries.filter(([, spec]) => spec.group === group).map(([id, spec]) =>
            <div key={id} className="flex min-h-7 items-center justify-between gap-2 px-2 text-meta">
              <span>{spec.label}</span><ShortcutHint id={id} />
            </div>)}
        </section>)}
      </div>
    </DialogContent>
  </Dialog>
}
