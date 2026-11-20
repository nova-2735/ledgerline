import { Moon, Sun } from 'lucide-react'
import type { Schemas } from '@/api/client'
import { ShortcutHint } from '@/components/ShortcutHint'
import { cn } from '@/lib/utils'

type Props = {
  health?: Schemas['HealthResponse']
  error: boolean
  ms?: number
  count?: number
  dark: boolean
  live?: boolean
  onHealth: () => void
  onTheme: () => void
  onHelp: () => void
}

export function healthLabel(health: Schemas['HealthResponse']) {
  const provider = health.llm_provider === 'gemini' ? 'Gemini' : health.llm_provider === 'fake' ? 'Offline reader (test data)' : health.llm_provider
  return [provider, health.llm_model, `OCR ${health.ocr_available ? 'on' : 'off'}`].filter(Boolean).join(' · ')
}

export function StatusBar({ health, error, ms, count, dark, live, onHealth, onTheme, onHelp }: Props) {
  const ThemeIcon = dark ? Sun : Moon
  return <footer aria-label="Workspace status" className="col-span-full flex h-7 min-w-0 items-center gap-2 border-t bg-card px-2 text-meta text-muted-foreground">
    <button type="button" onClick={onHealth} aria-label="API health" className="flex h-full min-w-0 items-center gap-2 px-1.5 hover:bg-muted">
      <span className={cn('size-2 shrink-0', error ? 'bg-reject' : live ? 'bg-primary' : health ? 'bg-approve' : 'bg-input')} aria-hidden="true" />
      <span className="shrink-0">{error ? 'API unavailable' : live ? 'Live' : health ? 'Connected' : 'Connecting'}</span>
      {health && <span className="hidden truncate sm:inline">· {healthLabel(health)}</span>}
      {ms != null && <span className="hidden shrink-0 md:inline">· API {ms} ms</span>}
    </button>
    {count != null && <span className="hidden shrink-0 border-l pl-2 sm:inline">{count} {count === 1 ? 'run' : 'runs'}</span>}
    <div className="ml-auto flex h-full shrink-0 items-center">
      <button type="button" aria-label={dark ? 'Use light theme' : 'Use dark theme'} onClick={onTheme} className="flex h-full items-center gap-1.5 border-l px-2 hover:bg-muted">
        <ThemeIcon className="size-3.5" aria-hidden="true" /><span className="hidden sm:inline">{dark ? 'Light' : 'Dark'}</span><ShortcutHint id="theme" />
      </button>
      <button type="button" onClick={onHelp} className="flex h-full items-center gap-1.5 border-l px-2 hover:bg-muted">
        <ShortcutHint id="help" /> Shortcuts
      </button>
    </div>
  </footer>
}
