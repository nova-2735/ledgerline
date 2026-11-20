import { render } from '@testing-library/react'
import { HighlightLayer } from '../HighlightLayer'

it('projects normalized bounding coordinates into precise percentages', () => {
  const { container } = render(<HighlightLayer page={1} active="total" showAll={false} highlights={[
    { id: 'total', label: 'Invoice total', level: 'low', bbox: [{ page: 1, x0: .1, y0: .2, x1: .3, y1: .25 }] },
  ]} />)
  const box = container.querySelector<HTMLElement>('[data-highlight="total"]')!
  expect([box.style.left, box.style.top, box.style.width, box.style.height]).toEqual(['10%', '20%', '20%', '5%'])
  expect(box.className).toContain('border-amber-600')
})
