import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

async function processInvoice(page: Page, scenario: string, outcome: string) {
  await page.goto('/inbox')
  await page.getByTestId('mail-' + scenario).click()
  await page.getByRole('button', { name: 'Process selected' }).click()
  await expect(page).toHaveURL(/\/runs\/\d+$/)
  await expect(page.getByTestId('run-decision')).toHaveAttribute('data-outcome', outcome)
}

async function review(page: Page, action: RegExp, bank = false) {
  await page.getByRole('button', { name: action }).first().click()
  const dialog = page.getByRole('dialog')
  if (bank) {
    await dialog.getByLabel('Called the number on file').check()
    await dialog.getByLabel('Spoke to a known contact').check()
  } else {
    await dialog.getByRole('radio').first().check()
    const verified = dialog.getByRole('checkbox')
    if (await verified.count()) await verified.check()
  }
  await dialog.getByLabel('Reviewer name').fill('Demo reviewer')
  await dialog.getByLabel('Note', { exact: true }).fill('Confirmed against the purchasing records.')
  await dialog.getByRole('button', { name: 'Record review' }).click()
  await expect(page.getByTestId('run-decision')).toHaveAttribute('data-version', '2')
  await expect(page.getByTestId('run-decision')).toHaveAttribute('data-outcome', 'APPROVE')
}

test('dashboard opens at 90D with seeded history', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '90D' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('heading',{name:'Recent runs'})).toBeVisible()
  await expect(page.getByText('R-0024',{exact:true}).first()).toBeVisible()
})

test('S01 approves with posting lines', async ({ page }) => {
  await processInvoice(page, 'S01', 'APPROVE')
  await expect(page.getByTestId('posting-lines').getByRole('row').first()).toBeVisible()
})

test('S04 resumes after purchase order confirmation', async ({ page }) => {
  await processInvoice(page,'S04','HOLD')
  await review(page,/Confirm PO/i)
  await expect(page.getByTestId('resume-divider')).toContainText(/resumed/i)
})

test('S06 requires bank verification before approval', async ({ page }) => {
  await processInvoice(page,'S06','HOLD')
  await expect(page.getByRole('button',{name:'Approve',exact:true})).toBeDisabled()
  await review(page,/Verify bank/i,true)
})

test('S05 rejects a duplicate and links to the original run', async ({ page }) => {
  await processInvoice(page,'S05','REJECT')
  const original = page.getByTestId('original-run')
  const href = await original.getAttribute('href')
  await original.click()
  await expect(page).toHaveURL(new RegExp(href + '$'))
  await expect(page.getByTestId('run-decision')).toHaveAttribute('data-outcome','APPROVE')
})

test('S11 blocks approval on the vendor-master check', async ({ page }) => {
  await processInvoice(page,'S11','HOLD')
  await expect(page.getByRole('button',{name:'Approve',exact:true})).toBeDisabled()
  await expect(page.getByText(/vendor master/i).first()).toBeVisible()
})

test('the palette jumps to a run and the shortcut sheet opens', async ({ page }) => {
  await page.goto('/')
  await page.keyboard.press('Control+k')
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox').fill('R-0001')
  await dialog.getByRole('option',{name:/R-0001/}).click()
  await expect(page).toHaveURL(/\/runs\/1$/)
  await page.keyboard.press('?')
  await expect(page.getByRole('heading',{name:'Keyboard shortcuts'})).toBeVisible()
})

test('previewing a higher price tolerance flips S12', async ({ page }) => {
  await processInvoice(page,'S12','HOLD')
  const id = new URL(page.url()).pathname
  await page.goto('/policy')
  await page.getByRole('button',{name:/Try policy changes|Edit policy/}).click()
  await page.getByLabel('Unit price tolerance (%)').fill('10')
  await page.getByLabel('Allowed invoice total difference (%)').fill('10')
  await page.getByLabel('Maximum invoice total difference (₹)').fill('5000')
  await page.getByRole('button',{name:'Preview impact'}).click()
  const row = page.getByRole('table',{name:'Policy impact'}).getByRole('row').filter({has:page.locator('a[href="' + id + '"]')})
  await expect(row.getByRole('group',{name:'Hold → Approve'})).toBeVisible()
})

test('the stress folder lists the unseen documents and U09 holds as two invoices', async ({ page }) => {
  await page.goto('/inbox?folder=stress')
  await expect(page.getByTestId('mail-U09')).toBeVisible()
  await expect(page.getByTestId('mail-S01')).toHaveCount(0)
  await processInvoice(page, 'U09', 'HOLD')
  await expect(page.getByText(/2 invoices/).first()).toBeVisible()
})

test('the audit PDF link downloads the run record as a PDF', async ({ page }) => {
  await processInvoice(page, 'S13', 'HOLD')
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: /Audit PDF/ }).click(),
  ])
  expect(download.suggestedFilename()).toMatch(/^R-\d{4}-audit\.pdf$/)
  const bytes = await readFile(await download.path())
  expect(bytes.subarray(0, 5).toString()).toBe('%PDF-')
})

test('resetting the demo says how long it took', async ({ page }) => {
  await page.goto('/')
  await page.keyboard.press('Control+k')
  const palette = page.getByRole('dialog')
  await palette.getByRole('combobox').fill('Reset')
  await palette.getByRole('option', { name: /Reset demo data/ }).click()
  await page.getByRole('button', { name: 'Reset demo data' }).click()
  await expect(page.getByText(/Demo data reset in \d+(\.\d)? s/)).toBeVisible()
  await expect(page.getByText(/Restored the seeded history/)).toBeVisible()
})
