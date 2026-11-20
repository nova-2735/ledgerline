import { render, screen } from '@testing-library/react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { periodDelta } from '@/lib/dashboard'
import { KpiTile } from '../KpiTile'

const kpis = (processed: number, value_processed: string, touchless_rate = 0) =>
  ({ processed, value_processed, touchless_rate, awaiting_review: 0, median_decision_ms: null, exposure_stopped: '0.00' })

describe('periodDelta', () => {
  it.each([
    ['no runs in the previous period', kpis(4, '400.00'), kpis(4, '400.00'), 'value_processed', 400, 'no-prior'],
    ['previous value is zero', kpis(6, '400.00'), kpis(4, '400.00'), 'value_processed', 400, 'no-prior'],
    ['previous value to compare with', kpis(6, '700.00'), kpis(4, '400.00'), 'value_processed', 400, 100],
    ['metric without a comparison', kpis(6, '700.00'), kpis(4, '400.00'), 'median_decision_ms', 1200, null],
  ] as const)('%s', (_, total, recent, metric, current, expected) => {
    expect(periodDelta(total, recent, metric, current)).toBe(expected)
  })
})

describe('KpiTile', () => {
  const tile = (delta: Parameters<typeof KpiTile>[0]['delta']) => render(<TooltipProvider>
    <KpiTile label="Processed" info="Runs" value="4" period="30D" series={[1, 2]} delta={delta} />
  </TooltipProvider>)

  it('shows "No prior data" instead of a delta when the previous period is empty', () => {
    tile('no-prior')
    expect(screen.getByText('No prior data').className).toContain('text-muted-foreground')
    expect(screen.queryByText(/vs prev/)).toBeNull()
  })

  it('shows the delta when there is prior data', () => {
    tile({ value: 2, text: '2' })
    expect(screen.getByText('▲ 2 vs prev 30D')).toBeTruthy()
  })
})
