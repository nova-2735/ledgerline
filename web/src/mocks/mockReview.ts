import { ApiError, type Schemas } from '@/api/client'
import { actions, outcomes, stages } from '@/lib/labels'
import { pendingStage, resumeStage, stageOrder } from '@/lib/runReducer'

type Run = Schemas['RunDetail']
type Request = Schemas['ReviewRequest']
type Event = Schemas['RunEvent']
const resolved = {
  confirm_po: ['PO_INFERRED', 'PO_AMBIGUOUS', 'PO_MISSING', 'PO_NOT_FOUND'],
  correct_fields: ['FIELD_LOW_CONFIDENCE', 'FIELD_MISSING_INVOICE_NUMBER', 'FIELD_MISSING_INVOICE_DATE', 'FIELD_MISSING_TOTAL', 'FIELD_MISSING_SUPPLIER'],
  verify_bank: ['BANK_DETAILS_CHANGED', 'SENDER_DOMAIN_MISMATCH'],
  not_duplicate: ['DUPLICATE_SUSPECTED', 'DUPLICATE_SAME_INVOICE', 'DUPLICATE_SAME_FILE'],
  approve: [], reject: [], send_to_vendor: [], reopen: [],
} satisfies Record<Request['action'], Schemas['ReasonCode'][]>

/** Mirrors the API's approve guard for the cases the mock world reaches. */
export function mockApprovalBlock(run: Omit<Run, 'approval_block'>): string | null {
  if (!run.decision) return null
  const critical = run.checks.find(check => check.severity === 'critical' && !check.resolved_by_review && (check.status === 'fail' || check.status === 'warn'))
  if (critical) {
    return `Can't approve while “${critical.title}” is unresolved. Resolve it first (for bank details: call the vendor on the number on file and record the call-back).`
  }
  if (!run.vendor_id) {
    return `Can't approve: ${run.vendor_name ?? 'the supplier'} isn't in the vendor master, so there's no vendor record to pay. Procurement must onboard the vendor first; until then, keep the invoice on hold or reject it.`
  }
  return null
}

export function mockReview(run: Run, request: Request, beforeEvents: Event[], now = Date.now()) {
  const previous = run.decision
  if (!request.reviewer?.trim() || !request.note?.trim() || !previous || run.status === 'running') {
    throw new ApiError(422, 'invalid_review', 'Enter your name and a note for a run ready to review.')
  }
  const blocked = mockApprovalBlock(run)
  if (request.action === 'approve' && blocked) throw new ApiError(409, 'critical_unresolved', blocked)
  if (request.action === 'confirm_po' && !request.po_number?.trim()) {
    throw new ApiError(422, 'missing_po', 'Enter a purchase order number.')
  }
  const at = (offset: number) => new Date(now + offset).toISOString()
  const version = previous.version + 1
  const codes: Schemas['ReasonCode'][] = [...resolved[request.action]]
  if (request.fields_verified) codes.push('FIELD_LOW_CONFIDENCE')
  const checks = run.checks.map(check => check.code && codes.includes(check.code) ? {
    ...check, resolved_by_review: true,
  } : check)
  const reasons = previous.reasons.filter(code => !codes.includes(code))
  const outcome = request.action === 'reject' ? 'REJECT' : request.action === 'send_to_vendor' ? 'RETURN' :
    request.action === 'approve' || (!reasons.length && request.action !== 'reopen') ? 'APPROVE' : 'HOLD'
  const status = outcome === 'HOLD' ? 'awaiting_review' : 'completed'
  const po = request.po_number ?? run.po_number
  const review: Schemas['ReviewAction'] = {
    id: run.review_actions.length + 1, run_id: run.id, action: request.action,
    reviewer: request.reviewer.trim(), note: request.note.trim(), po_number: request.po_number ?? null,
    fields_verified: request.fields_verified ?? null, field_corrections: request.field_corrections ?? null,
    resulting_decision_version: version, created_at: at(0),
  }
  const summary = outcome === 'APPROVE' ? 'The reviewer cleared the hold. The invoice is ready for payment.' :
    outcome === 'HOLD' ? 'The review has been recorded. Outstanding checks still need attention.' : 'The reviewer recorded a final decision.'
  const handoff = outcome === 'HOLD' && previous.handoff ? {
    ...previous.handoff, blocking_codes: reasons,
    ...(reasons.length === 1 && reasons[0] === 'FIELD_LOW_CONFIDENCE' ? {
      question: 'Can AP verify the highlighted fields on the invoice?',
      suggested_action: 'Check the printed values and record any corrections.',
      actions: ['correct_fields', 'reject'] as Request['action'][],
    } : {}),
  } : null
  const extraction = run.extraction ? { ...run.extraction } : null
  if (extraction) {
    for (const [key, value] of Object.entries(request.field_corrections ?? {})) {
      if (['invoice_number', 'invoice_date', 'supplier_gstin', 'total', 'bank_account_number'].includes(key)) {
        const field = key as 'invoice_number' | 'invoice_date' | 'supplier_gstin' | 'total' | 'bank_account_number'
        extraction[field] = { ...extraction[field], value }
      }
    }
  }
  const total = extraction?.total.value ?? run.total
  const match = run.matching && { ...run.matching, po_number: po }
  const route = outcome === 'HOLD' ? previous.route : 'none'
  const decision: Schemas['Decision'] = {
    ...previous, version, decided_at: at(1475), outcome, final: status === 'completed', route,
    primary_reason: outcome === 'APPROVE' ? null : reasons[0] ?? null,
    reasons: outcome === 'APPROVE' ? [] : reasons, headline: outcomes[outcome], handoff,
    explanation: { ...previous.explanation, summary, bullets: [], internal_note: null, vendor_message: null },
    notes: request.action === 'verify_bank' ? ['Update the vendor master through change control before payment.'] : [],
    posting: outcome === 'APPROVE' ? previous.posting ?? mockPosting(run, extraction, po, total) : null,
  }
  const eventLog = [...beforeEvents]
  const emit = (type: Event['type'], offset: number, message: string | null, data: Event['data'] = null,
    row?: Schemas['StageState'], stageStatus?: Event['status']) => eventLog.push({
    seq: (eventLog.at(-1)?.seq ?? 0) + 1, run_id: run.id, ts: at(offset), type, stage: row?.name ?? null,
    status: stageStatus ?? row?.status ?? null, message, data,
  })
  emit('review.recorded', 0, `${actions[review.action]} recorded`, { review })
  emit('run.resumed', 50, `Resumed after review by ${review.reviewer}${review.po_number ? ` · confirmed ${review.po_number}` : ''}`)
  const index = stageOrder.indexOf(resumeStage)
  const updatedStages = stageOrder.map((name, i) => {
    const original = run.stages.find(stage => stage.name === name) ?? pendingStage(name)
    if (i < index) return original
    const start = 100 + (i - index) * 400
    const duration = 170
    const stageChecks = checks.filter(check => check.stage === name)
    const status = stageChecks.some(check => check.status === 'fail' && !check.resolved_by_review) ? 'failed' : 'passed'
    const row: Schemas['StageState'] = {
      ...original, status, started_at: at(start), finished_at: at(start + duration), duration_ms: duration,
      summary: name === 'resolve_po' && po ? `Purchase order ${po} confirmed.` : `${stages[name]} complete.`,
      detail: name === 'resolve_po' ? { ...original.detail, method: 'confirmed', po_number: po } : original.detail,
    }
    emit('stage.started', start, null, null, row, 'running')
    emit('stage.completed', start + duration, row.summary, {
      checks: stageChecks, duration_ms: duration, detail: row.detail, check_rule_ids: row.check_rule_ids,
    }, row)
    if (name === 'decide') emit('decision.made', start + duration + 5, decision.headline, { decision })
    return row
  })
  emit(status === 'completed' ? 'run.completed' : 'run.awaiting_review', 2040, decision.headline)
  const reviewed: Omit<Run, 'approval_block'> = {
    ...run, status, outcome, total, route, po_number: po, checks, stages: updatedStages,
    final_outcome: status === 'completed' ? outcome : null, primary_reason: decision.primary_reason,
    invoice_date: extraction?.invoice_date.value ?? run.invoice_date, invoice_number: extraction?.invoice_number.value ?? run.invoice_number,
    decision, decision_history: [...run.decision_history, decision], review_actions: [...run.review_actions, review],
    duration_ms: (run.duration_ms ?? 0) + 2040, extraction, matching: match,
  }
  const detail: Run = { ...reviewed, approval_block: mockApprovalBlock(reviewed) }
  return { detail, events: eventLog }
}

function mockPosting(run: Run, extraction: Run['extraction'], po: string | null, total: string | null): Schemas['PostingPayload'] | null {
  if (!extraction || !run.vendor_id || !extraction.invoice_number.value || !extraction.invoice_date.value || !po || !total) return null
  const rao = run.scenario_id === 'S04'
  const due = new Date(extraction.invoice_date.value)
  due.setUTCDate(due.getUTCDate() + 30)
  return {
    vendor_id: run.vendor_id, invoice_number: extraction.invoice_number.value, invoice_date: extraction.invoice_date.value,
    total, currency: 'INR', due_date: due.toISOString().slice(0, 10), payment_terms_days: 30,
    remit_to: rao ? { bank_name: 'State Bank of India', account_number: '****8531' } :
      { bank_name: 'HDFC Bank', account_number: '****2741', ifsc: 'HDFC0001862' },
    lines: extraction.line_items.map((line, i) => ({
      po_number: po, po_line_no: i + 1, gl_account: rao ? '510600' : '530300',
      cost_center: rao ? 'BLR-MAINT' : 'BLR-QA-LAB', taxable_amount: line.taxable_amount ?? '0.00',
      tax_amount: (rao ? ['5130.00', '1476.00'] : ['6660.00', '1350.00'])[i] ?? '0.00',
      description: line.description,
    })),
  }
}
