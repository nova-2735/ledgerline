import { inr } from '@/lib/format'
import { fieldKeys, fieldLabels } from '@/lib/invoiceFields'
import { mockRunDocument } from './mockServer'

// Keep the mock page and its optional PDF available without checked-in generated files.
function invoiceCanvas(id: number, page: number) {
  const run = mockRunDocument(id)
  const extraction = run.extraction
  const sheet = document.createElement('canvas')
  sheet.width = 820
  sheet.height = 1120
  const canvas = sheet.getContext('2d')!
  const caption = (text: string, x: number, y: number, size = 17, color = '#172333', bold = false) => {
    canvas.fillStyle = color
    canvas.font = `${bold ? '600' : '400'} ${size}px Arial, sans-serif`
    canvas.fillText(text, x, y)
  }
  const rule = (y: number, color = '#d6dce3') => {
    canvas.fillStyle = color
    canvas.fillRect(65, y, 690, 1)
  }
  canvas.fillStyle = run.doc_kind === 'scanned' ? '#faf9f4' : '#fff'
  canvas.fillRect(0, 0, sheet.width, sheet.height)
  canvas.fillStyle = '#263d5b'
  canvas.fillRect(65, 45, 33, 33)
  caption('TAX INVOICE', 112, 69, 26, '#263d5b', true)
  caption(`Page ${page} of ${run.page_count}`, 664, 69, 13, '#4c5c71')
  rule(85, '#263d5b')
  if (extraction) {
    for (const key of fieldKeys) {
      const field = extraction[key]
      const box = field.bbox.find(item => item.page === page)
      if (!box || !field.raw) continue
      const x = box.x0 * sheet.width
      const y = box.y0 * sheet.height
      caption(fieldLabels[key].toUpperCase(), x, y - 2, 10, '#52637a', true)
      caption(field.raw, x + 3, y + 20, key === 'supplier_name' || key === 'total' ? 22 : 16, '#172333', key === 'total')
    }
    const headers = [['DESCRIPTION', 82], ['QTY', 495], ['UNIT PRICE', 555], ['AMOUNT', 663]] as const
    canvas.fillStyle = '#eef2f7'
    canvas.fillRect(65, 442, 690, 40)
    headers.forEach(([name, x]) => caption(name, x, 467, 12, '#263d5b', true))
    extraction.line_items.forEach((line, i) => {
      const y = 520 + i * 45
      caption(line.description, 82, y)
      caption(line.quantity ?? '—', 495, y)
      caption(inr(line.unit_price), 555, y, 15)
      caption(inr(line.amount), 663, y, 15)
      rule(y + 12)
    })
    caption('GST', 82, 735, 11, '#52637a', true)
    caption(inr(extraction.tax.total_tax), 84, 755, 17)
    if (extraction.annotations.length) caption(extraction.annotations[0], 440, 892, 20, '#315989', true)
  } else {
    caption(run.vendor_name ?? 'Invoice supplier', 80, 127, 22, '#172333', true)
    caption(run.invoice_number ?? 'Invoice number omitted', 80, 210)
    caption(run.po_number ?? 'Purchase order omitted', 80, 250)
    rule(280)
    caption('Total', 80, 336)
    caption(inr(run.total), 510, 336, 20, '#172333', true)
  }
  rule(1030)
  caption('Ledgerline · Synthetic demo invoice', 65, 1058, 13, '#52637a')
  return sheet
}

export const mockPageImage = (id: number, page: number) => invoiceCanvas(id, page).toDataURL('image/png')

export function mockOriginalPdf(id: number): Blob {
  const canvas = invoiceCanvas(id, 1)
  const jpeg = atob(canvas.toDataURL('image/jpeg', 0.9).split(',')[1])
  const drawing = 'q\n595 0 0 813 0 0 cm\n/Invoice Do\nQ\n'
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 813] /Resources << /XObject << /Invoice 4 0 R >> >> /Contents 5 0 R >>',
    `<< /Type /XObject /Subtype /Image /Width ${canvas.width} /Height ${canvas.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n${jpeg}\nendstream`,
    `<< /Length ${drawing.length} >>\nstream\n${drawing}endstream`,
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = objects.map((object, index) => {
    const start = pdf.length
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
    return String(start).padStart(10, '0')
  })
  const xref = pdf.length
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map(offset => `${offset} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return new Blob([Uint8Array.from(pdf, character => character.charCodeAt(0))], { type: 'application/pdf' })
}
