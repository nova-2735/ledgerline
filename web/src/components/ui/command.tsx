import type { ComponentProps } from 'react'
import { Command as Primitive } from 'cmdk'
import { Search } from 'lucide-react'
import { cn } from '@/lib/utils'

export function Command(props: ComponentProps<typeof Primitive>) {
  return <Primitive data-slot="command" {...props} />
}

export function CommandInput({ className, ...props }: ComponentProps<typeof Primitive.Input>) {
  return <div className="flex h-12 items-center gap-2 border-b px-3">
    <Search className="size-4 text-muted-foreground" aria-hidden="true" />
    <Primitive.Input className={cn('h-full w-full bg-transparent text-body outline-none! placeholder:text-muted-foreground', className)} {...props} />
  </div>
}

export function CommandList(props: ComponentProps<typeof Primitive.List>) {
  return <Primitive.List className="max-h-[min(62vh,460px)] overflow-y-auto p-1" {...props} />
}

export function CommandGroup(props: ComponentProps<typeof Primitive.Group>) {
  return <Primitive.Group className="p-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-meta [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground" {...props} />
}

export function CommandItem(props: ComponentProps<typeof Primitive.Item>) {
  return <Primitive.Item className="flex min-h-8 cursor-pointer items-center gap-2 rounded-sm px-2 text-body aria-disabled:opacity-50 data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground" {...props} />
}

export const CommandEmpty = Primitive.Empty
