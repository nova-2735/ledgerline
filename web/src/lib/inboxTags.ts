import type { InboxItem } from '@/api/client'

const labels: Record<string, string> = {
  'doc-type': 'Proforma', 'missing-field': 'Missing invoice no.', 'three-way': '3-way match', 'two-way': '2-way match',
  'po-inference': 'Missing PO', 'price-variance': 'Price difference', tax: 'GST', 're-keyed-number': 'Retyped number',
  stamp: 'Stamped', 'po-mismatch': 'PO mismatch', 'bank-change': 'Bank change', 'look-alike-domain': 'Similar email domain',
  'blanket-po': 'Blanket order', 'cumulative-billing': 'Cumulative billing', 'round-off': 'Rounding', tolerance: 'Within tolerance',
  'approval-limit': 'Approval limit', 'line-mapping': 'Bundled lines', 'western-format': 'Western number format',
  'tax-inclusive': 'Tax included', blocked: 'Blocked vendor', digital: 'Digital', scanned: 'Scanned', duplicate: 'Duplicate',
}
const hidden = new Set(['happy-path', 'human-in-the-loop', 'fraud-signal', 'approve', 'approved', 'hold', 'return', 'return-to-vendor', 'reject'])

export function inboxTags(mail?: InboxItem) {
  if (!mail) return []
  const tags = mail.tags.map(tag => tag.toLowerCase())
  const result = tags.filter(tag => !hidden.has(tag) && !tag.startsWith('expected-')).flatMap(tag => {
    if (tag === 'vendor-master') return tags.includes('blocked') ? [] : ['Unknown vendor']
    const words = tag.replaceAll('-', ' ')
    return [labels[tag] ?? words.charAt(0).toUpperCase() + words.slice(1)]
  })
  return result.sort((a, b) => Number(['Digital', 'Scanned'].includes(a)) - Number(['Digital', 'Scanned'].includes(b)))
}
