import type { Schemas } from '@/api/client'
import { fixtures } from '@/mocks/fixtures'
import { initialProgress, mergeRun, runReducer, stageOrder } from '../runReducer'

const finished = fixtures.events.S01.reduce(runReducer, initialProgress)

it('reconstructs all eleven stage states and the approval from the replay', () => {
  expect(finished.stages).toHaveLength(11)
  expect(finished.stages.map(row => [row.name, row.status, row.duration_ms]))
    .toEqual(fixtures.details.S01.stages.map(row => [row.name, row.status, row.duration_ms]))
  expect(finished.decision?.outcome).toBe('APPROVE')
  expect(mergeRun(fixtures.details.S01, finished, true).extraction?.total.value).toBe('116348.00')
})

it('ignores duplicate and out-of-order events', () => {
  expect(runReducer(finished, fixtures.events.S01.at(-1)!)).toBe(finished)
  expect(runReducer(finished, fixtures.events.S01[1])).toBe(finished)
})

it('keeps earlier stages and resets the last five after a review', () => {
  const hold = fixtures.events.S04.reduce(runReducer, initialProgress)
  const review: Schemas['ReviewAction'] = {
    id: 1, run_id: 28, reviewer: 'Priya Nair', note: 'Checked the scan', action: 'confirm_po',
    created_at: '2026-11-19T00:00:00Z', po_number: 'KF-PO-0151', field_corrections: null,
    fields_verified: true, resulting_decision_version: 2,
  }
  const event = { run_id: 28, ts: review.created_at, stage: null, status: null, message: null }
  const recorded = runReducer(hold, {
    ...event, seq: hold.lastSeq + 1, type: 'review.recorded', data: { review },
  })
  const resumed = runReducer(recorded, { ...event, seq: recorded.lastSeq + 1, type: 'run.resumed', data: null })
  expect(resumed.resumedMarkers).toMatchObject([{ review: { reviewer: 'Priya Nair', po_number: 'KF-PO-0151' } }])
  expect(resumed.stages.slice(0, 6)).toEqual(hold.stages.slice(0, 6))
  expect(resumed.stages.slice(6).map(row => [row.name, row.status])).toEqual(stageOrder.slice(6).map(name => [name, 'pending']))
  expect(mergeRun(fixtures.details.S04, resumed, true)).toMatchObject({ decision: null, status: 'running' })
})
