import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Schemas } from '@/api/client'
import { outcomeColors } from '../OutcomeBadge'
import { istDate } from '@/lib/format'
import { outcomes } from '@/lib/labels'

const series = Object.keys(outcomeColors) as Schemas['Outcome'][]
const shortLabel = { APPROVE: 'Approve', HOLD: 'Hold', RETURN: 'Return', REJECT: 'Reject' }
const axis = { fontSize: 11, fill: '#475569' }

export function DecisionsByDay({ data }: { data: Schemas['StatsDay'][] }) {
  return <section className="panel min-w-0 px-4 pt-4 pb-3 sm:px-5">
    <div className="mb-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <h2 className="section-title">Decisions per day</h2>
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
        {series.map(key => <span key={key} className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-[2px]" style={{ backgroundColor: outcomeColors[key] }} aria-hidden="true" />
          {shortLabel[key]}
        </span>)}
      </div>
    </div>
    {data.some(day => series.some(key => day[key] > 0)) ?
      <div className="h-[177px] min-w-0" aria-label="Daily invoice decisions">
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 640, height: 177 }}>
          <BarChart data={data} margin={{ top: 12, right: 8, bottom: 2, left: 0 }} accessibilityLayer>
            <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 4" />
            <XAxis dataKey="date" tickFormatter={value => istDate(String(value)).split(' ').slice(0, 2).join(' ')}
              minTickGap={23} tick={axis} axisLine={false} tickLine={false} tickMargin={9} />
            <YAxis allowDecimals={false} width={25} tick={axis} axisLine={false} tickLine={false} />
            <Tooltip labelFormatter={value => istDate(String(value))} cursor={{ fill: '#eef2ff' }} />
            {series.map(key => <Bar key={key} dataKey={key} name={outcomes[key]} stackId="decisions"
              fill={outcomeColors[key]} maxBarSize={16} isAnimationActive={false} />)}
          </BarChart>
        </ResponsiveContainer>
      </div>
      : <p className="grid h-[177px] place-items-center text-sm text-muted-foreground">No decisions in this period.</p>}
  </section>
}
