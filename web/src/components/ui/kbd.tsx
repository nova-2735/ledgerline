import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export function Kbd({ className, ...props }: ComponentProps<'kbd'>) {
  return <kbd data-slot="kbd" className={cn('inline-flex min-h-4 min-w-4 items-center justify-center rounded-sm border bg-card px-0.5 font-sans text-[10px] leading-none font-medium text-muted-foreground', className)} {...props} />
}

export function KbdGroup({ className, ...props }: ComponentProps<'span'>) {
  return <span data-slot="kbd-group" className={cn('inline-flex shrink-0 items-center gap-0.5', className)} {...props} />
}
