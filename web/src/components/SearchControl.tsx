import { Search } from 'lucide-react'
import type { Ref } from 'react'
import { ShortcutHint } from '@/components/ShortcutHint'
import { Input } from '@/components/ui/input'

export function SearchControl({ label, placeholder, inputRef, value, onChange }: {
  label: string; placeholder: string; inputRef: Ref<HTMLInputElement>; value: string; onChange: (value: string) => void
}) {
  return <label className="relative block w-60 max-w-full">
    <Search aria-hidden="true" className="pointer-events-none absolute top-2 left-2 size-4 text-muted-foreground" />
    <Input ref={inputRef} aria-label={label} placeholder={placeholder} value={value} onChange={event => onChange(event.target.value)}
      className="h-8 bg-card pl-8 pr-7 text-body" />
    <ShortcutHint id="search" className="pointer-events-none absolute top-2 right-2" />
  </label>
}
