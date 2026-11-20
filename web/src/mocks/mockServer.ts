import { ApiError, type RequestOptions, type Schemas } from '@/api/client'
import { outcomes, reasons, stages } from '@/lib/labels'
import { fixtures } from './fixtures'
import { mockReview } from './mockReview'
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
    policy_version: fixtures.policy.version,
  }
}

function makeDecision(run: Summary): Schemas['Decision'] | null {
  if (!run.outcome) return null
  const reason = run.primary_reason && reasons[run.primary_reason]
  const summary = reason || 'The invoice matches the order and passed the required checks.'
  return {
    version: 1, outcome: run.outcome, route: run.route ?? 'none', headline: outcomes[run.outcome],
    final: run.status === 'completed', primary_reason: run.primary_reason,
    reasons: run.primary_reason ? [run.primary_reason] : [], notes: [], posting: null,
    explanation: {
      summary, bullets: [], generated_by: 'template', model: null, vendor_message: null, internal_note: null,
    },
    checks_summary: {}, policy_version: fixtures.policy.version, decided_at: run.created_at,
    handoff: run.status === 'awaiting_review' ? {
      owner: run.route ?? 'ap_clerk',
      question: run.scenario_id === 'H23' ? 'Can Receiving confirm delivery of the 8 toner cartridges?' : summary,
      suggested_action: 'Review the invoice and supporting records.',
      blocking_codes: run.primary_reason ? [run.primary_reason] : [],
      amount_at_risk: run.total, actions: ['approve', 'reject', 'send_to_vendor'],
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
  return {
    ...emptyDetail(run), stages: stageNames.map((name, i) => stageAt(name, run, i)),
    decision, decision_history: decision ? [decision] : [],
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
  const original = scenarios[scenario ?? 'S01']
  const template = fixtures.details[scenario as keyof typeof fixtures.details] ?? genericDetail(original)
  const started = Date.now()
  const id = nextId++
  const cached = Boolean(scenario && !forceFresh && [...live.values()].some(({ detail }) => detail.scenario_id === scenario))
  const offset = started - Date.parse(template.created_at)
  const shift = (value: string | null) => value && iso(Date.parse(value) + offset)
  const decision = template.decision && { ...template.decision, decided_at: shift(template.decision.decided_at)! }
  const detail: Run = {
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

function getStats() {
  const base = structuredClone(fixtures.stats)
  const runs = [...live.keys()].map(currentRun).filter(run => run.outcome && run.status !== 'running')
  const timing = runs.flatMap(run => run.duration_ms == null ? [] : [run.duration_ms]).sort((a, b) => a - b)
  const total = base.kpis.processed + runs.length
  const queue = getQueue()
  const touchless = Math.round(base.kpis.processed * base.kpis.touchless_rate)
    + runs.filter(run => run.outcome === 'APPROVE' && !run.review_actions.length).length
  for (const run of runs) {
    const date = run.created_at.slice(0, 10)
    const day = base.by_day.find(item => item.date === date)
      ?? { date, APPROVE: 0, HOLD: 0, RETURN: 0, REJECT: 0 }
    if (!base.by_day.includes(day)) base.by_day.push(day)
    day[run.final_outcome ?? run.outcome!]++
    if (run.primary_reason && run.outcome !== 'APPROVE') {
      const reason = base.by_reason.find(item => item.code === run.primary_reason)
      if (reason) {
        reason.count++
        reason.amount = addMoney([reason.amount, run.total])
      } else {
        base.by_reason.push({ code: run.primary_reason, count: 1, amount: run.total ?? '0.00' })
      }
    }
  }
  return {
    ...base, by_route: Object.entries(queue.counts).map(([route, count]) => ({ route, count })),
    kpis: {
      ...base.kpis, processed: total, awaiting_review: queue.items.length,
      touchless_rate: total ? touchless / total : 0,
      value_processed: addMoney([base.kpis.value_processed, ...runs.map(run => run.total)]),
      exposure_stopped: addMoney([base.kpis.exposure_stopped, ...runs.map(run =>
        run.final_outcome === 'APPROVE' ? null : run.decision?.handoff?.amount_at_risk ?? null)]),
      median_decision_ms: timing.length ? (timing[Math.floor((timing.length - 1) / 2)] + timing[Math.floor(timing.length / 2)]) / 2 : null,
    },
  }
}

function addMoney(values: (string | null)[]) {
  const cents = values.reduce((sum, value) => {
    if (!value) return sum
    const [whole, fraction = ''] = value.replace(/^-/, '').split('.')
    const amount = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
    return sum + (value.startsWith('-') ? -amount : amount)
  }, 0n)
  const absolute = cents < 0 ? -cents : cents
  return `${cents < 0 ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`
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
    const number = decodeURIComponent(path.slice('/purchase-orders/'.length))
    if (number === fixtures.blanketOrder.po.po_number) return fixtures.blanketOrder
    const po = fixtures.orders.find(order => order.po_number === number)
    return po ? { po, balances: [], grns: [], runs: allRuns().filter(run => run.po_number === number) } : notFound()
  }
  switch (path) {
    case '/health': return fixtures.health
    case '/stats': return getStats()
    case '/runs': return listRuns(options.query)
    case '/queue': return getQueue(options.query)
    case '/vendors': return fixtures.vendors
    case '/purchase-orders':
      return fixtures.orders.filter(order =>
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
