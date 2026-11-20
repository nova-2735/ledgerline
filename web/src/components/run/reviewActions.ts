import type { Schemas } from '@/api/client'
import { shortcuts, type Shortcut } from '@/lib/shortcuts'
import { actions } from '@/lib/labels'

/** Why the API would refuse approve right now (its own guard, sent with the run). */
export function approvalBlock(run: Schemas['RunDetail']): string | undefined {
  return run.approval_block ?? undefined
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
