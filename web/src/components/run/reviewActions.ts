import type { Schemas } from '@/api/client'
import { shortcuts, type Shortcut } from '@/lib/shortcuts'
import { actions } from '@/lib/labels'

export function approvalBlock(run: Schemas['RunDetail']): string | undefined {
  const unresolved = run.checks.filter(check => !check.resolved_by_review && (check.status === 'fail' || check.status === 'warn'))
  if (unresolved.some(check => check.code === 'BANK_DETAILS_CHANGED')) return 'Verify the changed bank details before approving payment.'
  if (unresolved.some(check => check.severity === 'critical')) return 'Resolve the critical check before approving payment.'
}

export function reviewActions(run?: Schemas['RunDetail']) {
  return run?.decision?.handoff?.actions ?? []
}

export function primaryReviewAction(run?: Schemas['RunDetail']) {
  return reviewActions(run).find(action => action !== 'approve' || !approvalBlock(run!))
}

export function actionShortcut(action: Schemas['ActionType']): Shortcut | undefined {
  return action in shortcuts ? action as Shortcut : undefined
}

const shortLabels: Partial<Record<Schemas['ActionType'], string>> = {
  verify_bank: 'Verify bank', correct_fields: 'Correct fields', send_to_vendor: 'Send to vendor',
}

export function actionLabel(action: Schemas['ActionType']) {
  return shortLabels[action] ?? actions[action]
}
