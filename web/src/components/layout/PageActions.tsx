import { createContext, useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export const RunConnection = createContext<((live: boolean) => void) | null>(null)

export const PageActionsTarget = createContext<HTMLDivElement | null>(null)

export function PageActions({ children, inlineWhenUnavailable = false }: { children: ReactNode; inlineWhenUnavailable?: boolean }) {
  const target = useContext(PageActionsTarget)
  return target ? createPortal(children, target) : inlineWhenUnavailable ? <div className="mb-3 flex items-center gap-2">{children}</div> : null
}
