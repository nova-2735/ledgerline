import { Link } from 'react-router-dom'
import type { Schemas } from '@/api/client'
import { outcomeColors, StatusSquare } from '@/components/OutcomeBadge'
import { dayOutcomes, outcomeLabels } from '@/lib/dashboard'
import { istDate } from '@/lib/format'
import { cn } from '@/lib/utils'

type Day = Schemas['StatsDay']

export default function Decisions({ bars }: { bars: Day[] }) {
  const totals = dayOutcomes.map(outcome => bars.reduce((total, bar) => total + bar[outcome], 0))
  const scale = Math.max(4, Math.ceil(Math.max(...bars.map(bar => dayOutcomes.reduce((sum, outcome) => sum + bar[outcome], 0))) / 4) * 4)
  const labels = [0, Math.floor((bars.length - 1) / 3), Math.floor(2 * (bars.length - 1) / 3), bars.length - 1]
  return <div className="p-3">
    <div className="flex flex-wrap gap-x-4 gap-y-1 pb-2 text-meta">
      {dayOutcomes.map((outcome, index) => <span className="flex items-center gap-1.5" key={outcome}><StatusSquare outcome={outcome} />{outcomeLabels[outcome]} <span className="text-muted-foreground">{totals[index]}</span></span>)}
    </div>
    <div className="relative ml-5 h-[146px] border-b">
      {[0, 1, 2, 3, 4].map(step => <div key={step} className="pointer-events-none absolute inset-x-0 border-t" style={{ top: (step * 25) + '%' }}>
        <span className="absolute right-full -translate-y-1/2 pr-2 text-meta text-muted-foreground">{scale - step * scale / 4}</span>
      </div>)}
      <div className="relative grid h-full" style={{ gridTemplateColumns: 'repeat(' + bars.length + ', minmax(0,1fr))' }}>
        {bars.map((bar, index) => {
          const title = istDate(bar.date) + ' · ' + dayOutcomes.map(outcome => outcomeLabels[outcome] + ' ' + bar[outcome]).join(' · ')
          return <Link key={bar.date} tabIndex={dayOutcomes.some(key => bar[key]) ? 0 : -1} to={'/runs?date=' + bar.date} aria-label={title} title={title}
            className="group relative flex h-full min-w-0 items-end justify-center hover:bg-accent focus-visible:bg-accent">
            <span className="flex h-full w-[78%] max-w-3 flex-col-reverse">
              {dayOutcomes.map(outcome => <span key={outcome} className="block shrink-0" style={{ backgroundColor: outcomeColors[outcome], height: (bar[outcome] / scale * 100) + '%' }} />)}
            </span>
            {labels.includes(index) && <span className={cn('pointer-events-none absolute top-full mt-1 whitespace-nowrap text-meta text-muted-foreground', index === 0 ? 'left-0' : index === bars.length - 1 ? 'right-0' : 'left-1/2 -translate-x-1/2')}>
              {new Intl.DateTimeFormat('en-GB', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(bar.date))}</span>}
          </Link>
        })}
      </div>
    </div>
    <div className="h-4" />
  </div>
}
