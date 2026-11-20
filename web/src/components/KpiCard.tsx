import type { LucideIcon } from 'lucide-react'
import { Info } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Tooltip, TooltipContent, TooltipTrigger } from './ui/tooltip'

export function KpiCard({ title, value, icon: Icon, detail, to }: {
  title: string
  value: string | number
  icon: LucideIcon
  detail?: string
  to?: string
}) {
  return <article className="panel grid min-w-0 gap-3 px-4 py-3.5">
    <div className="flex items-center justify-between">
      <span className="grid size-8 place-items-center rounded-md bg-indigo-50 text-indigo-700"><Icon aria-hidden="true" className="size-4" /></span>
      {detail && <Tooltip>
        <TooltipTrigger asChild><button type="button" className="rounded p-1 text-slate-500 hover:text-indigo-700" aria-label={`About ${title.toLowerCase()}`}>
          <Info className="size-4" aria-hidden="true" />
        </button></TooltipTrigger>
        <TooltipContent className="max-w-64">{detail}</TooltipContent>
      </Tooltip>}
    </div>
    <div>
      <div className="text-xs font-medium leading-5 text-muted-foreground md:text-sm">{title}</div>
      <div className="mt-1 truncate text-xl font-semibold tracking-tight tabular-nums xl:text-[1.6rem]" title={String(value)}>
        {to ? <Link to={to} className="text-indigo-700 hover:underline" aria-label={`${value} ${title.toLowerCase()}`}>{value}</Link> : value}
      </div>
    </div>
  </article>
}
