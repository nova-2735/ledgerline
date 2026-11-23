import { useEffect, useEffectEvent } from 'react'

export const modifierLabel = /Mac|iPad|iPhone/i.test(navigator.platform) ? '⌘' : 'Ctrl'

export const destinations = [
  { id: 'dashboard', label: 'Dashboard', path: '/', key: 'D' },
  { id: 'inbox', label: 'Inbox', path: '/inbox', key: 'I' },
  { id: 'runs', label: 'Runs', path: '/runs', key: 'R' },
  { id: 'queue', label: 'Queue', path: '/queue', key: 'Q' },
  { id: 'orders', label: 'POs', path: '/purchase-orders', key: 'P' },
  { id: 'vendors', label: 'Vendors', path: '/vendors', key: 'V' },
  { id: 'policy', label: 'Policy', path: '/policy', key: 'Y' },
  { id: 'guide', label: 'How it works', path: '/how-it-works', key: 'H' },
] as const

const scopes = ['Lists', 'Dashboard', 'Runs', 'Inbox', 'Run view', 'Review'] as const
type Scope = 'Global' | 'Go to' | typeof scopes[number]
type Direction = 'next' | 'previous'
type Spec = { label: string; keys: readonly string[]; group: Scope }

export const shortcuts = {
  palette: { label: 'Open command palette', keys: [modifierLabel, 'K'], group: 'Global' },
  help: { label: 'Show shortcuts', keys: ['?'], group: 'Global' },
  sidebar: { label: 'Toggle sidebar', keys: ['['], group: 'Global' },
  theme: { label: 'Toggle theme', keys: ['T'], group: 'Global' },
  escape: { label: 'Close overlay or clear selection', keys: ['Esc'], group: 'Global' },
  dashboard: { label: 'Dashboard', keys: ['G', 'D'], group: 'Go to' },
  inbox: { label: 'Inbox', keys: ['G', 'I'], group: 'Go to' },
  runs: { label: 'Runs', keys: ['G', 'R'], group: 'Go to' },
  queue: { label: 'Queue', keys: ['G', 'Q'], group: 'Go to' },
  orders: { label: 'POs', keys: ['G', 'P'], group: 'Go to' },
  vendors: { label: 'Vendors', keys: ['G', 'V'], group: 'Go to' },
  policy: { label: 'Policy', keys: ['G', 'Y'], group: 'Go to' },
  guide: { label: 'How it works', keys: ['G', 'H'], group: 'Go to' },
  search: { label: 'Focus search or filters', keys: ['/'], group: 'Lists' },
  next: { label: 'Next row', keys: ['J'], group: 'Lists' },
  previous: { label: 'Previous row', keys: ['K'], group: 'Lists' },
  open: { label: 'Open selected row', keys: ['Enter'], group: 'Lists' },
  peek: { label: 'Peek at selected run', keys: ['Space'], group: 'Runs' },
  select: { label: 'Select row for export', keys: ['X'], group: 'Runs' },
  export: { label: 'Export CSV', keys: ['E'], group: 'Runs' },
  queueLink: { label: 'Open queue', keys: ['Q'], group: 'Dashboard' },
  week: { label: 'Last 7 days', keys: ['1'], group: 'Dashboard' },
  month: { label: 'Last 30 days', keys: ['2'], group: 'Dashboard' },
  quarter: { label: 'Last 90 days', keys: ['3'], group: 'Dashboard' },
  all: { label: 'All available days', keys: ['4'], group: 'Dashboard' },
  upload: { label: 'Upload PDF', keys: ['U'], group: 'Inbox' },
  processAll: { label: 'Process all unprocessed', keys: ['Shift', 'B'], group: 'Inbox' },
  previewMessage: { label: 'Focus message preview', keys: ['Space'], group: 'Inbox' },
  process: { label: 'Process invoice', keys: ['P'], group: 'Inbox' },
  fresh: { label: 'Process with fresh read', keys: ['Shift', 'P'], group: 'Inbox' },
  decision: { label: 'Decision tab', keys: ['1'], group: 'Run view' },
  fields: { label: 'Fields tab', keys: ['2'], group: 'Run view' },
  matching: { label: 'Matching tab', keys: ['3'], group: 'Run view' },
  audit: { label: 'Audit tab', keys: ['4'], group: 'Run view' },
  highlights: { label: 'Toggle highlights', keys: ['H'], group: 'Run view' },
  prevRun: { label: 'Previous run', keys: ['['], group: 'Run view' },
  nextRun: { label: 'Next run', keys: [']'], group: 'Run view' },
  prevStage: { label: 'Expand previous stage', keys: ['↑'], group: 'Run view' },
  nextStage: { label: 'Expand next stage', keys: ['↓'], group: 'Run view' },
  approve: { label: 'Approve', keys: ['A'], group: 'Review' },
  reject: { label: 'Reject', keys: ['R'], group: 'Review' },
  confirm_po: { label: 'Confirm PO', keys: ['C'], group: 'Review' },
  verify_bank: { label: 'Verify bank', keys: ['V'], group: 'Review' },
  correct_fields: { label: 'Correct fields', keys: ['E'], group: 'Review' },
  send_to_vendor: { label: 'Send to vendor', keys: ['S'], group: 'Review' },
} as const satisfies Record<string, Spec>

export type Shortcut = keyof typeof shortcuts
type Handlers = Partial<Record<Shortcut, () => void>>
export const shortcutEntries = Object.entries(shortcuts) as [Shortcut, Spec][]
export const shortcutGroups: Scope[] = ['Global', 'Go to', ...scopes]

export function rowIndex(index: number, count: number, direction: Direction) {
  if (!count) return -1
  if (index < 0) return direction === 'next' ? 0 : count - 1
  return Math.max(0, Math.min(count - 1, index + (direction === 'next' ? 1 : -1)))
}

const invokeEvent = 'ledgerline:shortcut'
const normalize = (key: string) => ({ ' ': 'space', escape: 'esc', arrowup: '↑', arrowdown: '↓' }[key.toLowerCase()] ?? key.toLowerCase())

export function invokeShortcut(id: Shortcut) {
  window.dispatchEvent(new CustomEvent(invokeEvent, { detail: id }))
}

export function useShortcuts(handlers: Handlers, enabled = true, modalScope?: string) {
  const currentHandlers = useEffectEvent(() => handlers)

  useEffect(() => {
    if (!enabled) return
    let prefixAt = -Infinity

    function onKey(event: KeyboardEvent) {
      const target = event.target instanceof Element ? event.target : document.activeElement
      const editable = target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]')
      const overlay = [...document.querySelectorAll('[role="dialog"][data-state="open"], [role="menu"][data-state="open"]')].at(-1)
      if (event.defaultPrevented || event.isComposing || event.altKey || editable ||
        (overlay && (!modalScope || overlay.getAttribute('data-shortcut-scope') !== modalScope))) {
        prefixAt = -Infinity
        return
      }
      const key = normalize(event.key)
      const handlers = currentHandlers()
      if ((key === 'enter' || key === 'space') && target?.closest('button, a, [role="button"], [role="tab"]')) return
      const command = event.metaKey || event.ctrlKey
      const prefix = performance.now() - prefixAt < 900
      prefixAt = -Infinity
      if (!command && !event.shiftKey && key === 'g' && destinations.some(({ id }) => handlers[id])) {
        if (!event.repeat) prefixAt = performance.now()
        event.preventDefault()
        return
      }

      const match = shortcutEntries.find(([id, spec]) => {
        if (!handlers[id] || key !== normalize(spec.keys.at(-1)!)) return false
        const first = spec.keys[0]
        if (first === 'G' && spec.keys.length === 2) return prefix && !command && !event.shiftKey
        if (first === modifierLabel && spec.keys.length === 2) return command && !event.shiftKey
        if (command || prefix) return false
        if (first === 'Shift') return event.shiftKey
        return !event.shiftKey || key === '?'
      })
      if (!match) return
      event.preventDefault()
      if (!event.repeat || ['next', 'previous', 'prevStage', 'nextStage'].includes(match[0])) handlers[match[0]]?.()
    }

    function onInvoke(event: Event) {
      currentHandlers()[(event as CustomEvent<Shortcut>).detail]?.()
    }

    const capture = destinations.some(({ id }) => currentHandlers()[id])
    window.addEventListener('keydown', onKey, capture)
    window.addEventListener(invokeEvent, onInvoke)
    return () => {
      window.removeEventListener('keydown', onKey, capture)
      window.removeEventListener(invokeEvent, onInvoke)
    }
  }, [enabled, modalScope])
}
