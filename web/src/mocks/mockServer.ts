import { dayBefore } from '@/lib/dashboard'
import { dayOf } from '@/lib/runList'
import { ApiError, type RequestOptions, type Schemas } from '@/api/client'
import { outcomes, reasons, stages } from '@/lib/labels'
import { fixtures } from './fixtures'
import { mockApprovalBlock, mockReview } from './mockReview'
import { scenarios } from './scenarios'

type Run = Schemas['RunDetail']
type RunEvent = Schemas['RunEvent']
type Summary = Schemas['RunSummary']
type Stage = Schemas['StageState']
type Scenario = keyof typeof scenarios

const live = new Map<number, { detail: Run; events: RunEvent[] }>()
const previewIds = new Map<string, number>()
let nextId = fixtures.runs.total + 1
const seeded = fixtures.runs.items
const terminalEvents = ['run.completed', 'run.awaiting_review', 'run.failed']
const stageNames = Object.keys(stages) as Schemas['StageName'][]
const iso = (value: number) => new Date(value).toISOString()

function emptyDetail(run: Summary): Run {
  return {
    ...run, stages: [], checks: [], matching: null, extraction: null, decision: null,
    decision_history: [], review_actions: [], page_count: 1, file_sha256: '0'.repeat(64),
    policy_version: fixtures.policy.version, approval_block: null,
  }
}

function makeDecision(run: Summary): Schemas['Decision'] | null {
  if (!run.outcome) return null
  const reason = run.primary_reason && reasons[run.primary_reason]
  const priceReview = run.scenario_id === 'S12'
  const summary = priceReview ? 'The supplier billed ₹662.00 per roll against ₹610.00 on the purchase order.' :
    reason || 'The invoice matches the order and passed the required checks.'
  const codes: Schemas['ReasonCode'][] = run.primary_reason ? [run.primary_reason] : []
  if (priceReview) codes.push('AMOUNT_VARIANCE_OVER_TOL')
  const vendorReturn = run.outcome === 'RETURN' && run.status === 'awaiting_review'
  return {
    version: 1, outcome: run.outcome, route: run.route ?? 'none', headline: outcomes[run.outcome],
    final: run.status === 'completed', primary_reason: run.primary_reason,
    reasons: codes, notes: [], posting: null,
    explanation: {
      summary, bullets: [], generated_by: 'template', model: null, internal_note: null,
      vendor_message: vendorReturn && run.sender_email ? {
        channel: 'email', to: fixtures.vendors.find(vendor => vendor.vendor_id === run.vendor_id)?.email ?? run.sender_email,
        subject: `Invoice ${run.invoice_number ?? run.display_id} needs attention`,
        body: `Please send a corrected tax invoice. ${summary}.`,
      } : null,
    },
    checks_summary: {}, policy_version: fixtures.policy.version, decided_at: run.created_at,
    handoff: run.status === 'awaiting_review' ? {
      owner: run.route ?? 'ap_clerk',
      question: run.scenario_id === 'H23' ? 'Can Receiving confirm delivery of the 8 toner cartridges?' :
        priceReview ? 'Did the buyer agree to pay ₹662.00 per roll?' : summary,
      suggested_action: 'Review the invoice and supporting records.',
      blocking_codes: codes,
      amount_at_risk: priceReview ? '3681.60' : run.total,
      actions: vendorReturn ? ['send_to_vendor'] : ['approve', 'reject', 'send_to_vendor'],
    } : null,
  }
}

function stageAt(name: Stage['name'], run: Summary, index: number): Stage {
  const started = Date.parse(run.created_at) + 80 + index * 180 + (index > 2 ? 4000 : 0)
  const duration = index === 2 ? 4000 : 100
  return {
    name, status: 'passed', duration_ms: duration, started_at: iso(started), finished_at: iso(started + duration),
    summary: `${stages[name]} complete.`, check_rule_ids: [], detail: {},
  }
}

function genericDetail(run: Summary): Run {
  const decision = makeDecision(run)
  const billed = run.scenario_id === 'H01' ? { quantity: '40', amount: '58000.00', before: '0' }
    : run.scenario_id === 'H02' ? { quantity: '20', amount: '29000.00', before: '40' } : null
  return {
    ...emptyDetail(run), stages: stageNames.map((name, i) => stageAt(name, run, i)),
    decision, decision_history: decision ? [decision] : [],
    matching: billed ? {
      po_number: run.po_number, match_type: 'three_way', po_candidates: [],
      header_expected: run.total, header_invoiced: run.total, header_variance: '0.00',
      rows: [{
        kind: 'one_to_one', matched_by: 'code', invoice_line_indexes: [1], po_line_nos: [1],
        description_invoice: 'Nitrile gloves', description_po: 'Nitrile gloves', similarity: 1,
        qty_invoiced: billed.quantity, qty_ordered: '100', qty_received: billed.quantity,
        qty_available: billed.quantity, qty_billed_before: billed.before,
        unit_price_invoice: '1450.00', unit_price_po: '1450.00', price_variance_pct: '0.00',
        amount_expected: billed.amount, amount_invoice: billed.amount, status: 'pass', codes: [],
      }],
    } : null,
  }
}

function makeEvents(run: Run): RunEvent[] {
  const events: RunEvent[] = []
  const emit = (
    type: RunEvent['type'], ts: string, stage: RunEvent['stage'] = null, status: RunEvent['status'] = null,
    message: string | null = null, data: RunEvent['data'] = null,
  ) => events.push({ seq: events.length + 1, run_id: run.id, ts, type, stage, status, message, data })
  emit('run.created', run.created_at)
  emit('run.started', run.created_at)
  for (const stage of run.stages) {
    emit('stage.started', stage.started_at ?? run.created_at, stage.name, 'running')
    emit('stage.completed', stage.finished_at ?? run.created_at, stage.name, stage.status, stage.summary, {
      duration_ms: stage.duration_ms, detail: stage.detail, check_rule_ids: stage.check_rule_ids,
    })
  }
  const last = events.at(-1)?.ts ?? run.created_at
  if (run.decision) emit('decision.made', last, null, null, run.decision.headline, { decision: run.decision })
  emit(run.status === 'awaiting_review' ? 'run.awaiting_review' : 'run.completed', last)
  return events
}

function createRun(scenarioId?: string, fileName?: string, forceFresh = false) {
  if (scenarioId && !Object.hasOwn(scenarios, scenarioId)) notFound()
  const scenario = scenarioId as Scenario | undefined
  const summary = scenarios[scenario ?? 'S01']
  const original: Summary = summary.outcome === 'RETURN' ? { ...summary, status: 'awaiting_review', final_outcome: null } : summary
  const template = fixtures.details[scenario as keyof typeof fixtures.details] ?? genericDetail(original)
  const started = Date.now()
  const id = nextId++
  const cached = Boolean(scenario && !forceFresh && [...live.values()].some(({ detail }) => detail.scenario_id === scenario))
  const offset = started - Date.parse(template.created_at)
  const shift = (value: string | null) => value && iso(Date.parse(value) + offset)
  const decision = template.decision && { ...template.decision, decided_at: shift(template.decision.decided_at)! }
  const created: Omit<Run, 'approval_block'> = {
    ...template, id, display_id: `R-${String(id).padStart(4, '0')}`, created_at: iso(started),
    filename: fileName ?? template.filename, source: scenario ? 'demo' : 'upload', scenario_id: scenario ?? null,
    sender_name: scenario ? template.sender_name : null, sender_email: scenario ? template.sender_email : null,
    subject: scenario ? template.subject : null, cached_extraction: cached,
    extraction: template.extraction && { ...template.extraction, meta: { ...template.extraction.meta, cached } },
    decision, decision_history: decision ? [decision] : [],
    stages: template.stages.map(stage => ({
      ...stage, started_at: shift(stage.started_at), finished_at: shift(stage.finished_at),
      detail: stage.name === 'extract_fields' ? { ...stage.detail, cached } : stage.detail,
    })),
  }
  const detail: Run = { ...created, approval_block: mockApprovalBlock(created) }
  const replay = fixtures.events[scenario as keyof typeof fixtures.events]
  const events = replay ? replay.map(event => ({
    ...event, run_id: id, ts: shift(event.ts)!,
    data: event.type === 'decision.made' ? { ...event.data, decision } : event.data,
  })) : makeEvents(detail)
  live.set(id, { detail, events })
  return { run_id: id } satisfies Schemas['RunCreated']
}

function currentRun(id: number): Run {
  const record = live.get(id)
  if (!record) {
    const run = seeded.find(item => item.id === id)
    return run ? genericDetail(run) : notFound()
  }
  const { detail, events } = record
  const last = events.at(-1)!
  if (Date.parse(last.ts) <= Date.now()) return detail
  const available = events.filter(event => Date.parse(event.ts) <= Date.now())
  const resumed = events.findLast(event => event.type === 'run.resumed')
  const elapsed = resumed ? available.filter(event => event.seq > resumed.seq) : available
  const finished = new Set(elapsed.filter(event => event.type === 'stage.completed').map(event => event.stage))
  if (resumed) for (const name of stageNames.slice(0, 6)) finished.add(name)
  const started = new Set(elapsed.filter(event => event.type === 'stage.started').map(event => event.stage))
  const decided = elapsed.some(event => event.type === 'decision.made')
  return {
    ...detail, status: 'running', duration_ms: null, final_outcome: null,
    outcome: decided ? detail.outcome : null, route: decided ? detail.route : null,
    primary_reason: decided ? detail.primary_reason : null, decision: decided ? detail.decision : null,
    decision_history: decided ? detail.decision_history : [],
    extraction: finished.has('extract_fields') ? detail.extraction : null,
    matching: finished.has('match_lines') ? detail.matching : null,
    checks: detail.checks.filter(check => finished.has(check.stage)),
    stages: detail.stages.map(stage => finished.has(stage.name) ? stage : {
      ...stage, status: started.has(stage.name) ? 'running' : 'pending',
      started_at: started.has(stage.name) ? stage.started_at : null,
      finished_at: null, duration_ms: null, summary: null, check_rule_ids: [], detail: {},
    }),
  }
}

function allRuns() {
  return [...Array.from(live.keys()).reverse().map(currentRun), ...seeded.filter(run => !live.has(run.id))]
}

function mockPurchaseOrder(number: string): Schemas['PurchaseOrderDetail'] {
  const order = fixtures.orders.find(item => item.po_number === number)
  if (!order) return notFound()
  const { billed_value: _billed, ordered_value: _ordered, pct_billed: _pct, ...po } = order
  const blanket = number === fixtures.blanketOrder.po.po_number ? fixtures.blanketOrder : null
  const runs = allRuns().filter(run => run.po_number === number)
  const grns = blanket?.grns ?? (po.match_type === 'three_way' && number !== 'KF-PO-0120' ? po.lines.map(line => ({
    grn_number: `GRN-${number.slice(-4)}`, po_number: number, line_no: line.line_no,
    quantity_received: line.quantity, received_date: '2026-11-09',
  })) : [])
  const balances = po.lines.map(line => {
    const base = blanket?.balances.find(item => item.line_no === line.line_no)
    const approved = runs.filter(run => run.final_outcome === 'APPROVE' && run.source !== 'seed')
    const seen = new Set<string>()
    const contributions = approved.flatMap(run => {
      if (run.invoice_number && seen.has(run.invoice_number)) return []
      if (run.invoice_number) seen.add(run.invoice_number)
      const detail = currentRun(run.id)
      const row = detail.matching?.rows.find(match => match.po_line_nos.length === 1 && match.po_line_nos[0] === line.line_no)
      if (!row?.qty_invoiced) return []
      const amount = row.status === 'fail' ? Math.min(Number(row.qty_invoiced), Number(row.qty_available ?? 0)) : Number(row.qty_invoiced)
      return amount > 0 ? [{ id: run.id, amount }] : []
    })
    const seededQuantity = base?.billed ?? (number === 'KF-PO-0126' ? line.quantity : '0')
    const seededInvoices = base?.invoices ?? runs.filter(run => run.source === 'seed' && run.final_outcome === 'APPROVE').map(run => run.id)
    const billed = Number(seededQuantity) + contributions.reduce((sum, item) => sum + item.amount, 0)
    const received = grns.filter(grn => grn.line_no === line.line_no).reduce((sum, receipt) => sum + Number(receipt.quantity_received), 0)
    return {
      line_no: line.line_no, po_number: number, ordered: line.quantity, received: String(received), billed: String(billed),
      remaining_to_bill: String(Math.max(0, Number(line.quantity) - billed)),
      received_unbilled: po.match_type === 'three_way' ? String(Math.max(0, received - billed)) : null,
      invoices: [...seededInvoices, ...contributions.map(item => item.id)],
    }
  })
  return { po, balances, grns, runs }
}

function mockOrders(): Schemas['PurchaseOrderOut'][] {
  return fixtures.orders.map(order => {
    const detail = mockPurchaseOrder(order.po_number)
    let billedCents = 0n
    for (const line of order.lines) {
      const billed = detail.balances.find(balance => balance.line_no === line.line_no)?.billed ?? '0'
      billedCents += BigInt(billed) * toCents(line.unit_price)
    }
    const orderedCents = toCents(order.ordered_value)
    const hundredths = orderedCents ? (billedCents * 10_000n + orderedCents / 2n) / orderedCents : 0n
    return { ...order, billed_value: moneyString(billedCents), pct_billed: moneyString(hundredths) }
  })
}

function listRuns({ q, offset = 0, limit = 50, ...filters }: NonNullable<RequestOptions['query']> = {}) {
  const search = typeof q === 'string' ? q.trim().toLowerCase() : ''
  const matches = allRuns().filter(run =>
    Object.entries(filters).every(([key, value]) => !value || run[key as keyof Summary] === value)
    && (!search || [run.vendor_name, run.invoice_number, run.po_number].some(value => value?.toLowerCase().includes(search))),
  )
  return { items: matches.slice(Number(offset), Number(offset) + Number(limit)), total: matches.length }
}

function getQueue(route?: RequestOptions['query']) {
  const items = [...live.keys()].reverse().map(currentRun).filter(run => run.status === 'awaiting_review').map<Schemas['QueueItem']>(run => ({
    ...run, question: run.decision?.handoff?.question ?? 'Review the invoice.',
    amount_at_risk: run.decision?.handoff?.amount_at_risk ?? null,
    age_hours: (Date.now() - Date.parse(run.created_at)) / 3_600_000,
  })).concat(fixtures.queue.items.filter(run => !live.has(run.id)))
  const counts: Record<string, number> = {}
  for (const item of items) {
    if (item.route) counts[item.route] = (counts[item.route] ?? 0) + 1
  }
  return { counts, items: route?.route ? items.filter(item => item.route === route.route) : items }
}

function getStats(days = 30): Schemas['StatsResponse'] {
  const queue = getQueue()
  const today = [fixtures.health.today, ...[...live.keys()].map(id => dayOf(currentRun(id).created_at))].sort().at(-1)!
  const first = dayBefore(today, days - 1)
  const runs = fixtures.runs.items.filter(run => !live.has(run.id)).concat([...live.keys()].map(currentRun))
    .filter(run => run.outcome && run.status !== 'running' && dayOf(run.created_at) >= first)
  const daysByDate = new Map<string, Schemas['StatsDay']>(Array.from({ length: days }, (_, i) => {
    const date = dayBefore(today, days - i - 1)
    return [date, { date, APPROVE: 0, HOLD: 0, RETURN: 0, REJECT: 0 }] as const
  }))
  const reasons = new Map<Schemas['ReasonCode'], Schemas['StatsReason']>()
  const routes = new Map<Schemas['Route'], number>()
  const risk: (string | null)[] = []
  const timings: number[] = []
  let touchless = 0
  for (const run of runs) {
    const firstDecision = live.has(run.id) ? currentRun(run.id).decision_history[0] : null
    const outcome = run.final_outcome ?? run.outcome!
    daysByDate.get(dayOf(run.created_at))![outcome]++
    if ((firstDecision?.outcome ?? run.outcome) === 'APPROVE' && (!live.has(run.id) || !currentRun(run.id).review_actions.length)) touchless++
    if (run.source !== 'seed' && run.duration_ms != null) timings.push(run.duration_ms)
    const reason = firstDecision?.primary_reason ?? run.primary_reason
    const route = firstDecision?.route ?? run.route
    if ((firstDecision?.outcome ?? run.outcome) !== 'APPROVE' && reason) {
      const previous = reasons.get(reason)
      reasons.set(reason, { code: reason, count: (previous?.count ?? 0) + 1, amount: addMoney([previous?.amount ?? null, run.total]) })
      if (route && route !== 'none') routes.set(route, (routes.get(route) ?? 0) + 1)
    }
    if (run.final_outcome !== 'APPROVE') {
      risk.push(live.has(run.id) ? currentRun(run.id).decision?.handoff?.amount_at_risk ?? null :
        reason?.startsWith('DUPLICATE_') ? run.total : null)
    }
  }
  timings.sort((a, b) => a - b)
  return {
    by_day: Array.from(daysByDate.values()),
    by_reason: Array.from(reasons.values()).sort((a, b) => b.count - a.count),
    by_route: Array.from(routes, ([route, count]) => ({ route, count })),
    kpis: {
      processed: runs.length, awaiting_review: queue.items.length,
      touchless_rate: runs.length ? touchless / runs.length : 0,
      value_processed: addMoney(runs.map(run => run.total)), exposure_stopped: addMoney(risk),
      median_decision_ms: timings.length ? (timings[Math.floor((timings.length - 1) / 2)] + timings[Math.floor(timings.length / 2)]) / 2 : null,
    },
  }
}

function addMoney(values: (string | null)[]) {
  return moneyString(values.reduce((sum, value) => sum + toCents(value ?? '0'), 0n))
}

function toCents(value: string) {
  const [whole, fraction = ''] = value.replace(/^-/, '').split('.')
  const amount = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  return value.startsWith('-') ? -amount : amount
}

function moneyString(cents: bigint) {
  const absolute = cents < 0 ? -cents : cents
  return `${cents < 0 ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`
}

function previewPolicy(request: Schemas['PolicyPreviewRequest']): Schemas['PolicyPreviewResponse'] {
  const tolerances = request.overrides?.tolerances as { unit_price_pct?: unknown; header_abs?: unknown } | undefined
  const approval = request.overrides?.approval as { auto_approve_limit?: unknown } | undefined
  const unit = Number(tolerances?.unit_price_pct ?? 2)
  const header = String(tolerances?.header_abs ?? '2500.00')
  const approvalLimit = String(approval?.auto_approve_limit ?? '500000.00')
  if (![header, approvalLimit].every(value => /^\d+(\.\d{1,2})?$/.test(value)) || !Number.isFinite(unit) ||
    unit < 0 || !Number.isSafeInteger(request.limit) || request.limit < 1) {
    throw new ApiError(422, 'invalid_policy_preview', 'Enter valid policy limits and try again.')
  }
  const limit = toCents(approvalLimit)
  const runs = allRuns().filter(run => run.outcome && (run.status === 'completed' || run.status === 'awaiting_review'))
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, request.limit)
  const changes = runs.flatMap<Schemas['PolicyPreviewChange']>(run => {
    const detail = currentRun(run.id)
    const before = run.final_outcome ?? run.outcome!
    const amount = run.total ? toCents(run.total) : 0n
    const reasonsBefore = detail.decision?.reasons ?? []
    const identity = { run_id: run.id, display_id: run.display_id }
    if (detail.review_actions.length) return []
    if (run.scenario_id === 'S12' && before === 'HOLD' && unit >= 8.53 && toCents(header) >= 312_000n && amount <= limit) {
      return [{ ...fixtures.policyPreview.changed[0], ...identity }]
    }
    if (run.primary_reason === 'APPROVAL_LIMIT_EXCEEDED' && before === 'HOLD' && amount <= limit) {
      return [{ ...identity, before, after: 'APPROVE', reasons_before: reasonsBefore, reasons_after: [] }]
    }
    if (before === 'APPROVE' && run.outcome === 'APPROVE' && amount > limit) {
      return [{ ...identity, before, after: 'HOLD', reasons_before: reasonsBefore,
        reasons_after: ['APPROVAL_LIMIT_EXCEEDED', ...reasonsBefore] }]
    }
    return []
  })
  return { changed: changes, unchanged: runs.length - changes.length }
}

function notFound(): never {
  throw new ApiError(404, 'not_found', 'We could not find that record.')
}

export function mockRequest(method: string, path: string, options: RequestOptions = {}): unknown {
  if (method === 'POST' && path.startsWith('/demo/runs/')) {
    return createRun(decodeURIComponent(path.slice('/demo/runs/'.length)), undefined,
      Boolean((options.json as Schemas['DemoRunRequest'] | undefined)?.force_fresh))
  }
  if (method === 'POST' && path === '/runs') {
    const file = options.form?.get('file')
    if (!(file instanceof File) || !/\.pdf$/i.test(file.name)) throw new ApiError(400, 'invalid_file', 'Choose a PDF file.')
    if (file.size > 10 * 1024 * 1024) throw new ApiError(413, 'file_too_large', 'The PDF must be 10 MB or smaller.')
    return createRun(undefined, file.name)
  }
  if (method === 'POST' && path === '/demo/reset') {
    live.clear()
    previewIds.clear()
    nextId = fixtures.runs.total + 1
    return { status: 'ok', runs: seeded.length }
  }
  if (method === 'POST' && path === '/policy/preview') return previewPolicy(options.json as Schemas['PolicyPreviewRequest'])
  const review = /^\/runs\/(\d+)\/review$/.exec(path)
  if (method === 'POST' && review) {
    const id = Number(review[1])
    const run = currentRun(id)
    live.set(id, mockReview(run, options.json as Schemas['ReviewRequest'], live.get(id)?.events ?? makeEvents(run)))
    return currentRun(id)
  }
  if (method !== 'GET') return notFound()
  const match = /^\/runs\/(\d+)(\/audit)?$/.exec(path)
  if (match) {
    const run = currentRun(Number(match[1]))
    if (!match[2]) return run
    return { run, events: live.get(run.id)?.events ?? makeEvents(run), raw_model_output: run.extraction?.meta.raw ?? null }
  }
  if (path.startsWith('/purchase-orders/')) {
    return mockPurchaseOrder(decodeURIComponent(path.slice('/purchase-orders/'.length)))
  }
  switch (path) {
    case '/health': return fixtures.health
    case '/stats': return getStats(Number(options.query?.days ?? 30))
    case '/runs': return listRuns(options.query)
    case '/queue': return getQueue(options.query)
    case '/vendors': return fixtures.vendors
    case '/purchase-orders':
      return mockOrders().filter(order =>
        (!options.query?.vendor_id || order.vendor_id === options.query.vendor_id)
        && (!options.query?.status || order.status === options.query.status),
      )
    case '/policy': return fixtures.policy
    case '/demo/inbox':
      return fixtures.inbox.map(item => ({
        ...item, processed_run_ids: [...live.values()].filter(({ detail }) =>
          detail.scenario_id === item.doc_id).map(({ detail }) => detail.id),
      }))
    default: return notFound()
  }
}

export function openMockScenario(scenario: string): number {
  const current = previewIds.get(scenario)
  if (current !== undefined) return current
  const { run_id } = createRun(scenario, undefined, true)
  previewIds.set(scenario, run_id)
  return run_id
}

export function mockRunDocument(id: number) {
  return live.get(id)?.detail ?? currentRun(id)
}

export function replayMockEvents(
  id: number, after: number, onEvent: (event: RunEvent) => void, onEnd: () => void,
) {
  const record = live.get(id)
  let events: RunEvent[]
  try {
    events = record?.events ?? makeEvents(currentRun(id))
  } catch {
    const timer = setTimeout(onEnd, 0)
    return () => clearTimeout(timer)
  }
  const remaining = events.filter(event => event.seq > after)
  const timers = remaining.map(event => setTimeout(() => {
    onEvent(event)
    if (terminalEvents.includes(event.type)) onEnd()
  }, Math.max(0, record ? Date.parse(event.ts) - Date.now() : 0)))
  if (!remaining.length) timers.push(setTimeout(onEnd, 0))
  return () => timers.forEach(clearTimeout)
}
