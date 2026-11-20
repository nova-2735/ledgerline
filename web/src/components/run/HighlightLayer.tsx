import type { Schemas } from '@/api/client'
import { cn } from '@/lib/utils'

export interface Highlight {
  id: string
  label: string
  level: Schemas['ConfidenceLevel']
  bbox: Schemas['BBox'][]
}

const percent = (value: number) => `${Number((value * 100).toFixed(8))}%`

export function HighlightLayer({ highlights, page, active, showAll }: {
  highlights: Highlight[]
  page: number
  active: string | null
  showAll: boolean
}) {
  return <div className="pointer-events-none absolute inset-0" aria-hidden="true">
    {highlights.filter(item => showAll || item.id === active).flatMap(item =>
      item.bbox.filter(box => box.page === page).map(({ x0, x1, y0, y1 }, i) =>
        <div key={`${item.id}-${i}`} data-highlight={item.id}
          className={cn('absolute border-[1.5px]', item.level === 'low' ? 'border-amber-600 border-dashed' : 'border-primary',
            active === item.id && 'z-10')}
          style={{ borderColor: item.level === 'low' ? 'var(--hold)' : undefined, left: percent(x0), top: percent(y0), width: percent(x1 - x0), height: percent(y1 - y0) }}>
          {active === item.id && <span className={cn('absolute bottom-full left-0 whitespace-nowrap rounded-t px-1.5 py-0.5 text-meta font-medium text-primary-foreground',
            item.level === 'low' ? 'bg-hold text-white' : 'bg-primary')}>{item.label}</span>}
        </div>,
      ),
    )}
  </div>
}
