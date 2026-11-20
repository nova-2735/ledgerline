import { ShortcutHint } from '@/components/ShortcutHint'
import { Button } from '@/components/ui/button'

export function RowKeys({ onStep, disabled }: { onStep: (direction: 'previous' | 'next') => void; disabled?: boolean }) {
  return <div className="flex shrink-0 items-center gap-1">
    <Button type="button" size="sm" variant="ghost" disabled={disabled} aria-label="Previous row" onClick={() => onStep('previous')}>
      <ShortcutHint id="previous" />
    </Button>
    <Button type="button" size="sm" variant="ghost" disabled={disabled} aria-label="Next row" onClick={() => onStep('next')}>
      <ShortcutHint id="next" />
    </Button>
  </div>
}
