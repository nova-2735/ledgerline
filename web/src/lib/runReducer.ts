import type { Schemas } from '@/api/client'
import { stages } from './labels'

type Event = Schemas['RunEvent']
type Stage = Schemas['StageState']
type Decision = Schemas['Decision']
type Review = Schemas['ReviewAction']
type Check = Schemas['CheckResult']
type Detail = Schemas['RunDetail']

export const stageOrder = Object.keys(stages) as Stage['name'][]
export const resumeStage = 'resolve_po'

export function pendingStage(name: Stage['name']): Stage {
  return {
    name, status: 'pending', started_at: null, finished_at: null, duration_ms: null,
    summary: null, check_rule_ids: [], detail: {},
  }
}

export interface RunProgress {
  stages: Stage[]
  events: Event[]
  lastSeq: number
  lastLog: Event | null
  decision: Decision | null
  status: Schemas['RunStatus'] | null
  resumedMarkers: { seq: number; ts: string; message: string; review: Review | null }[]
  review: Review | null
  checks: Record<string, Check>
}

export const initialProgress: RunProgress = {
  stages: stageOrder.map(pendingStage), events: [], lastSeq: 0, lastLog: null, decision: null,
  status: null, resumedMarkers: [], review: null, checks: {},
}

/** One rule can report several results (one per required field, say), so key by occurrence. */
export function keyedChecks(checks: Check[]): [string, Check][] {
  const seen = new Map<string, number>()
  return checks.map(check => {
    const n = seen.get(check.rule_id) ?? 0
    seen.set(check.rule_id, n + 1)
    return [`${check.rule_id}#${n}`, check]
  })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseDecision(value: unknown): Decision | null {
  return isRecord(value) && typeof value.version === 'number' && isRecord(value.explanation)
    ? value as Decision : null
}

function parseReview(value: unknown): Review | null {
  return isRecord(value) && typeof value.reviewer === 'string' && typeof value.action === 'string'
    ? value as Review : null
}

export function runReducer(state: RunProgress, event: Event): RunProgress {
  if (event.seq <= state.lastSeq) return state
  const next = { ...state, lastSeq: event.seq, events: [...state.events, event] }
  const { stage: name, type, data, ts } = event

  if (type === 'run.started') next.status = 'running'
  if (type === 'run.completed') next.status = 'completed'
  if (type === 'run.failed') next.status = 'failed'
  if (type === 'run.awaiting_review') next.status = 'awaiting_review'
  if (type === 'stage.log') next.lastLog = event
  if (type === 'decision.made') next.decision = parseDecision(data?.decision ?? data)
  if (type === 'review.recorded') next.review = parseReview(data?.review ?? data?.review_action ?? data)
  if (type === 'run.resumed') {
    const index = stageOrder.indexOf(resumeStage)
    next.stages = state.stages.map((row, i) => i < index ? row : pendingStage(row.name))
    next.checks = Object.fromEntries(Object.entries(state.checks).filter(([, check]) => stageOrder.indexOf(check.stage) < index))
    next.lastLog = null
    next.decision = null
    next.status = 'running'
    next.resumedMarkers = [...state.resumedMarkers, {
      seq: event.seq, ts, message: event.message ?? 'Resumed after review', review: next.review,
    }]
  }
  if (!name || (type !== 'stage.started' && type !== 'stage.completed')) return next
  const row = state.stages.find(item => item.name === name) ?? pendingStage(name)
  const checks = Array.isArray(data?.checks) ? data.checks as Check[] : []
  const finished = type === 'stage.completed'
  const elapsed = row.started_at ? Math.max(0, Date.parse(ts) - Date.parse(row.started_at)) : null
  const duration = data?.duration_ms
  const ids = data?.check_rule_ids
  const updated: Stage = finished ? {
    ...row, status: event.status ?? 'passed', finished_at: ts,
    duration_ms: typeof duration === 'number' ? duration : elapsed,
    summary: event.message, detail: isRecord(data?.detail) ? data.detail : {},
    check_rule_ids: Array.isArray(ids) ? ids.filter(id => typeof id === 'string') : checks.map(check => check.rule_id),
  } : { ...pendingStage(name), status: 'running', started_at: ts }
  next.stages = state.stages.map(item => item.name === name ? updated : item)
  if (checks.length) next.checks = { ...state.checks, ...Object.fromEntries(keyedChecks(checks)) }
  if (state.lastLog?.stage === name) next.lastLog = null
  return next
}

export function mergeRun(snapshot: Detail, progress: RunProgress, animate: boolean): Detail {
  if (!animate && !progress.resumedMarkers.length) return snapshot
  const status = progress.status ?? snapshot.status
  const lastResume = progress.resumedMarkers.at(-1)
  const lastDecision = progress.events.findLast(event => event.type === 'decision.made')
  const canShowDecision = lastDecision && (!lastResume || lastDecision.seq > lastResume.seq)
  const decision = canShowDecision ? (progress.decision ?? snapshot.decision) : null
  const allowed = new Set(progress.stages.filter(row => !['running', 'pending'].includes(row.status)).map(row => row.name))
  const checks = new Map(keyedChecks(snapshot.checks).filter(([, check]) => allowed.has(check.stage)))
  for (const [key, check] of Object.entries(progress.checks)) {
    if (!checks.get(key)?.resolved_by_review || check.resolved_by_review) checks.set(key, check)
  }
  const mergedStages = progress.stages.map(stage => {
    const saved = snapshot.stages.find(row => row.name === stage.name)
    if (!saved || (lastResume && stageOrder.indexOf(stage.name) >= stageOrder.indexOf(resumeStage)
      && (!stage.started_at || (saved.started_at && Date.parse(saved.started_at) < Date.parse(lastResume.ts))))) return stage
    if (stage.status === 'pending' && lastResume) return saved
    if (!allowed.has(stage.name)) return stage
    return {
      ...stage, duration_ms: saved.finished_at === stage.finished_at ? saved.duration_ms ?? stage.duration_ms : stage.duration_ms,
      summary: stage.summary ?? saved.summary, detail: { ...saved.detail, ...stage.detail },
      check_rule_ids: stage.check_rule_ids.length ? stage.check_rule_ids : saved.check_rule_ids,
    }
  })
  return {
    ...snapshot, status, stages: mergedStages, checks: [...checks.values()], decision,
    outcome: decision?.outcome ?? null, final_outcome: decision?.final ? decision.outcome : null,
    duration_ms: status === 'running' || status === 'queued' ? null : snapshot.duration_ms,
    extraction: allowed.has('extract_fields') ? snapshot.extraction : null,
    matching: allowed.has('match_lines') ? snapshot.matching : null,
  }
}
