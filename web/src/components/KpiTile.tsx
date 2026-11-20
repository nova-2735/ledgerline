import type { ReactNode } from 'react'
import { Info } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export function KpiTile({ label, info, value, delta, series, period }: {
  label: string; info: string; value: string
  delta?: { value: number; text: string; tone?: 'good' | 'bad' } | 'no-prior'
  series: number[]; period: string
}) {
  if (delta === 'no-prior') return <Tile label={label} info={info} value={value} series={series}>
    <div className="mt-0.5 min-h-4 truncate text-meta text-muted-foreground">No prior data</div>
  </Tile>
  return <Tile label={label} info={info} value={value} series={series}>
    <div className={cn('mt-0.5 min-h-4 truncate text-meta text-muted-foreground', delta?.tone === 'good' && 'text-approve', delta?.tone === 'bad' && 'text-reject')}>
      {delta ? <span title={delta.text + ' vs previous ' + period}>{delta.value > 0 ? '▲ ' : delta.value < 0 ? '▼ ' : ''}{delta.text} vs prev {period}</span> : <span aria-hidden="true">—</span>}
    </div>
  </Tile>
}

function Tile({ label, info, value, series, children }: { label: string; info: string; value: string; series: number[]; children: ReactNode }) {
  return <div className="min-w-0 bg-card px-3 py-2.5">
    <div className="flex items-center justify-between gap-1">
      <h2 className="truncate text-meta font-medium text-muted-foreground" title={label}>{label}</h2>
      <Tooltip>
        <TooltipTrigger asChild><button type="button" aria-label={'About ' + label} className="grid size-5 shrink-0 place-items-center text-muted-foreground hover:text-primary"><Info aria-hidden="true" className="size-3.5" /></button></TooltipTrigger>
        <TooltipContent>{info}</TooltipContent>
      </Tooltip>
    </div>
    <div className="mt-0.5 text-metric tracking-[-0.01em]" title={value}>{value}</div>
    {children}
    <Sparkline values={series} />
  </div>
}

function Sparkline({ values }: { values: number[] }) {
  if (!values.length) return <div className="h-6" />
  const low = Math.min(0, ...values), range = Math.max(1, Math.max(...values) - low)
  const points = values.map((value, index) => [3 + (index * 154) / Math.max(1, values.length - 1), 22 - 19 * (value - low) / range])
  const last = points.at(-1)!
  return <svg viewBox="0 0 160 24" preserveAspectRatio="none" className="mt-1 block h-6 w-full overflow-visible" aria-hidden="true">
    <polyline points={points.map(pair => pair.join(',')).join(' ')} fill="none" stroke="var(--faint-ink)" strokeWidth="1.25" vectorEffect="non-scaling-stroke" />
    <circle cx={last[0]} cy={last[1]} r="2" fill="var(--interactive)" />
  </svg>
}
