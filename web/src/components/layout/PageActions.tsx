import { createContext, useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export const RunConnection = createContext<((live: boolean) => void) | null>(null)

export const PageActionsTarget = createContext<HTMLDivElement | null>(null)

export function PageActions({ children }: { children: ReactNode }) {
  const target = useContext(PageActionsTarget)
  return target ? createPortal(children, target) : null
}
