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
