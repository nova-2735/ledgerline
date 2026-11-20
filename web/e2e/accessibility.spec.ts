import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const pages = [
  ['Dashboard', '/', 'table[aria-label="Exceptions by reason"]'],
  ['Inbox', '/inbox', 'button[id^="mail-"]'],
  ['Runs', '/runs', 'tbody tr'],
  ['Run record', '/runs/1', '#stage-toggle-intake'],
  ['Queue', '/queue', 'tbody tr'],
  ['Purchase orders', '/purchase-orders', 'tbody tr'],
  ['Order detail', '/purchase-orders/KF-PO-0119', 'tbody tr'],
  ['Vendors', '/vendors', 'tbody tr'],
  ['Policy', '/policy', '#policy-tolerances'],
  ['How it works', '/how-it-works', 'a[href*="folder=edge"]'],
] as const

for (const theme of ['light', 'dark']) {
  for (const [label, path, ready] of pages) {
    test(label + ' passes accessibility checks in ' + theme, async ({ page }) => {
      await page.addInitScript(value => localStorage.setItem('ledgerline-theme', value), theme)
      await page.goto(path)
      await expect(page.locator(ready).first()).toBeVisible()
      await page.evaluate(() => document.fonts.ready)
      const { violations } = await new AxeBuilder({ page }).analyze()
      const failures = violations.filter(v => v.impact === 'serious' || v.impact === 'critical')
        .map(v => ({ rule: v.id, nodes: v.nodes.map(n => n.target) }))
      expect(failures).toEqual([])
    })
  }
}
