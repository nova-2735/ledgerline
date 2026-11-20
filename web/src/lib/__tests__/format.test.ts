import { duration, inr, istDate, istTime, maskedBank, pct, relativeTime } from '../format'

it('formats money with Indian grouping and rounds half up', () => {
  expect(inr('116348.00')).toBe('₹1,16,348.00')
  expect(inr('116348.005')).toBe('₹1,16,348.01')
  expect(inr(null)).toBe('—')
})

it('handles timestamps and date-only values in IST', () => {
  expect(istDate('2026-11-12')).toBe('12 Nov 2026')
  expect(istDate('2026-11-11T21:00:00Z')).toBe('12 Nov 2026')
  expect(istTime('2026-11-12T11:10:00Z')).toBe('16:40 IST')
  expect(relativeTime('2026-11-12T11:10:00Z', Date.parse('2026-11-12T13:10:00Z'))).toBe('2 h ago')
})

it('masks bank accounts and formats fractional rates and latency', () => {
  expect(maskedBank('50200087654321')).toBe('•••• 4321')
  expect(maskedBank('****4321')).toBe('•••• 4321')
  expect(maskedBank('123')).toBe('—')
  expect(pct(0.79)).toBe('79%')
  expect(duration(5500)).toBe('5.5 s')
})
