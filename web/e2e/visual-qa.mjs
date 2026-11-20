import { chromium, expect } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../reports/visual/', import.meta.url))
const baseURL = process.env.WEB_URL ?? 'http://127.0.0.1:5173'
const phase = process.argv[2] ?? 'pages'
if (!['pages','confirmed','offline','empty'].includes(phase)) throw Error('Use pages, confirmed, empty or offline.')
if (!['127.0.0.1','localhost','[::1]'].includes(new URL(baseURL).hostname)) throw Error('Use a local stack.')
const code = process.env.DEMO_ACCESS_CODE
const get = async route => {
  const response = await fetch(new URL('/api' + route,baseURL),{ headers:code ? {'X-Access-Code':code} : {} })
  if (!response.ok) throw Error(route+' returned '+response.status)
  return response.json()
}
await mkdir(root,{recursive:true})
const provenance = path.join(root,'stack.json')
let ids
if (phase !== 'offline') {
  if ((await get('/health')).llm_provider !== 'gemini') throw Error('Use Gemini for screenshots.')
  if (phase === 'empty') {
    if ((await get('/queue')).items.length) throw Error('The unfiltered review queue must be empty.')
  } else {
    const inbox = await get('/demo/inbox')
    ids = Object.fromEntries(inbox.map(doc=>[doc.doc_id,doc.processed_run_ids.at(-1)]))
    await writeFile(provenance,JSON.stringify({baseURL,provider:'gemini',ids}))
  }
} else {
  const previous = JSON.parse(await readFile(provenance,'utf8'))
  if (previous.provider !== 'gemini' || previous.baseURL !== baseURL) throw Error('Capture the online stack first.')
  if (await get('/health').then(()=>true,()=>false)) throw Error('Stop the local QA API before the offline capture.')
}

const browser = await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL || (process.platform==='win32'?'msedge':'chromium')})
try {
  if (phase === 'confirmed') {
    const current = await get('/runs/'+ids.S04)
    if (current.decision?.version === 1) {
      const context = await browser.newContext({baseURL,viewport:{width:1440,height:900}})
      const page = await context.newPage()
      if (code) await page.addInitScript(c=>sessionStorage.setItem('ledgerline-access',c),code)
      await page.goto('/runs/'+ids.S04)
      await page.getByRole('button',{name:/Confirm PO/i}).click()
      const dialog = page.getByRole('dialog')
      await dialog.getByLabel('Reviewer name').fill('Demo buyer')
      await dialog.getByLabel('Note',{exact:true}).fill('Matched the invoice fields and confirmed the purchase order.')
      const fields = dialog.getByRole('checkbox')
      if (await fields.count()) await fields.check()
      await dialog.getByRole('button',{name:'Record review'}).click()
      await expect(page.getByText('v2',{exact:true})).toBeVisible({timeout:60000})
      await context.close()
    }
    await expect.poll(async()=> (await get('/runs/'+ids.S04)).decision?.outcome).toBe('APPROVE')
  }
  for (const [width,height] of [[1280,800],[1440,900],[1920,1080]]) {
    await Promise.all(['light','dark'].map(async theme => {
      const dir = path.join(root,width+'x'+height,theme)
      await mkdir(dir,{recursive:true})
      const context = await browser.newContext({baseURL,viewport:{width,height},reducedMotion:'reduce'})
      await context.addInitScript(({theme,code})=>{
        localStorage.setItem('ledgerline-theme',theme)
        if(code) sessionStorage.setItem('ledgerline-access',code)
      },{theme,code})
      const page = await context.newPage()
      const audit = {}
      async function save(name) {
        await page.evaluate(async()=>{ await document.fonts.ready; await Promise.all([...document.images].map(img=>img.decode())) })
        audit[name] = await page.evaluate(()=>({
          overflow:document.documentElement.scrollWidth-innerWidth,
          clipped:[...document.querySelectorAll('.truncate')].filter(el=>el.clientWidth>0 && el.scrollWidth>el.clientWidth+1 && !el.closest('[title]') && !el.querySelector('[title]')).map(el=>el.textContent),
        }))
        await page.screenshot({path:path.join(dir,name+'.png')})
      }
      async function visit(route,ready) {
        await page.goto(route)
        await expect(page.locator(ready).first()).toBeVisible()
        await page.waitForLoadState('networkidle')
      }
      async function run(scenario,name,outcome) {
        const record=await get('/runs/'+ids[scenario])
        if(record.decision?.outcome!==outcome) throw Error(scenario+' expected '+outcome)
        await visit('/runs/'+ids[scenario],'[data-stage]')
        if(width<1360) await page.getByRole('button',{name:'Decision and evidence'}).click()
        await expect(page.getByRole('heading',{name:record.decision.headline,exact:true}).first()).toBeVisible()
        await save(name)
      }
      try {
        if (phase==='pages') {
          for(const [name,route,ready] of [
            ['dashboard','/','table[aria-label="Invoices that need attention"] tbody tr'],['inbox','/inbox?doc=S06','section[aria-label="Last run decision"]'],
            ['runs','/runs','tbody tr'],['queue','/queue','tbody tr'],['orders','/purchase-orders','tbody tr'],['order-detail','/purchase-orders/KF-PO-0119','tbody tr'],
            ['vendors','/vendors','tbody tr'],['policy','/policy','#policy-tolerances'],['how-it-works','/how-it-works','a[href*="folder=edge"]'],
          ]) { await visit(route,ready); await save(name) }
          for (const [s,n,o] of [['S01','approve','APPROVE'],['S04','inferred-po','HOLD'],['S05','duplicate','REJECT'],['S06','run','HOLD'],['S09','return','RETURN']]) await run(s,n,o)
          const queue=await get('/queue')
          const owner=['controller','procurement','vendor','buyer','treasury','receiving','ap_clerk'].find(r=>!queue.items.some(i=>i.route===r))
          await page.goto('/queue?route='+owner)
          await expect(page.getByText(/Nothing waiting/)).toBeVisible()
          await save('empty-owner-folder')
          await visit('/inbox','button[id^="mail-"]')
          await page.locator('input[type=file]').setInputFiles({name:'notes.txt',mimeType:'text/plain',buffer:Buffer.from('Not a PDF')})
          await expect(page.getByText(/notes.txt must be a PDF/)).toBeVisible()
          await save('upload-error')
          await page.keyboard.press('Control+k')
          await expect(page.getByRole('dialog')).toBeVisible()
          await save('palette')
          await page.keyboard.press('Escape')
          await page.keyboard.press('?')
          await expect(page.getByRole('heading',{name:'Keyboard shortcuts'})).toBeVisible()
          await save('shortcuts')
        } else if (phase==='confirmed') await run('S04','confirmed-po','APPROVE')
        else if (phase === 'empty') { await page.goto('/queue'); await expect(page.getByRole('heading',{name:'Nothing waiting'})).toBeVisible(); await save('empty-queue') }
        else { await page.goto('/runs'); await expect(page.getByRole('button',{name:'Retry'}).first()).toBeVisible(); await save('api-error') }
        await writeFile(path.join(dir,phase+'.json'),JSON.stringify(audit,null,2))
        const broken = Object.entries(audit).filter(([, result]) => result.overflow > 0 || result.clipped.length)
        if (broken.length) throw Error(width + '×' + height + ' ' + theme + ': ' + JSON.stringify(broken))
      } finally { await context.close() }
    }))
  }
} finally {await browser.close()}
