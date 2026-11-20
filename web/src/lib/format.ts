const currency = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })
const percent = new Intl.NumberFormat('en-IN', { style: 'percent', maximumFractionDigits: 1 })
const date = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata',
})
const time = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Kolkata',
})

export function inr(value: string | null | undefined): string {
  if (value == null || !/^-?\d+(\.\d+)?$/.test(value)) return '—'
  // Intl accepts decimal strings without converting them to floating point.
  return currency.format(value as unknown as number)
}

export function pct(value: number | string | null | undefined): string {
  return value == null || !Number.isFinite(Number(value)) ? '—' : percent.format(Number(value))
}

export function istDate(value: string | null | undefined): string {
  return value ? date.format(new Date(value)) : '—'
}

export function istTime(value: string): string {
  return `${time.format(new Date(value))} IST`
}

export function relativeTime(value: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.floor((now - Date.parse(value)) / 60_000))
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes} min ago`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} h ago`
  return `${Math.floor(minutes / 1440)} d ago`
}

export function maskedBank(value: string | null | undefined): string {
  const lastFour = value?.match(/\d{4}$/)?.[0]
  return lastFour ? `•••• ${lastFour}` : '—'
}

export function duration(value: number | null | undefined): string {
  return value == null ? '—' : `${(value / 1000).toFixed(1)} s`
}
