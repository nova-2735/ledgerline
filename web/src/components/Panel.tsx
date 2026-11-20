import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Panel({ title, action, className, children, ...props }: Omit<ComponentProps<'section'>, 'title'> & { title?: string; action?: ReactNode }) {
  return <section className={cn('min-w-0 bg-card', className)} {...props}>
    {title && <header className="panel-title"><h2 className="text-section">{title}</h2>{action}</header>}
    {children}
  </section>
}
