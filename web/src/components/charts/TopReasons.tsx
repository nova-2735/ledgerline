import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Schemas } from '@/api/client'
import { inr } from '@/lib/format'
import { reasons } from '@/lib/labels'

export function TopReasons({ data }: { data: Schemas['StatsReason'][] }) {
  const ranked = [...data].sort((a, b) => b.count - a.count).slice(0, 8).map(row => ({ ...row, label: reasons[row.code] }))
  return <section className="panel min-w-0 px-4 pt-4 pb-3 sm:px-5">
    <h2 className="section-title mb-2">Why invoices didn’t go straight through</h2>
    {ranked.length ?
      <div className="h-[177px] min-w-0" aria-label="Most common reasons for invoice exceptions">
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 420, height: 177 }}>
          <BarChart layout="vertical" data={ranked} margin={{ top: 8, right: 12, bottom: 2, left: 0 }} accessibilityLayer>
            <CartesianGrid horizontal={false} stroke="#e2e8f0" strokeDasharray="3 4" />
            <XAxis type="number" allowDecimals={false} axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#475569' }} />
            <YAxis type="category" dataKey="label" width="auto" tick={{ fontSize: 11, fill: '#475569' }} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: '#eef2ff' }} formatter={(value, _name, item) => [
              `${value} ${value === 1 ? 'invoice' : 'invoices'} · ${inr((item.payload as Schemas['StatsReason']).amount)}`, 'Total',
            ]} />
            <Bar dataKey="count" fill="#6366f1" radius={[0, 4, 4, 0]} maxBarSize={16} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      : <p className="grid h-[177px] place-items-center text-sm text-muted-foreground">No invoice exceptions in this period.</p>}
  </section>
}
