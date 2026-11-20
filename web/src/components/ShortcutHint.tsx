import { Kbd, KbdGroup } from '@/components/ui/kbd'
import { shortcuts, type Shortcut } from '@/lib/shortcuts'

export function ShortcutHint({ id, className }: { id: Shortcut; className?: string }) {
  return <KbdGroup className={className} aria-hidden="true">{shortcuts[id].keys.map(key => <Kbd key={key}>{key}</Kbd>)}</KbdGroup>
}
