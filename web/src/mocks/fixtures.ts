import type { Schemas } from '@/api/client'
import eventsS01 from './events_S01.json'
import eventsS04 from './events_S04.json'
import eventsS06 from './events_S06.json'
import health from './health.json'
import inbox from './inbox.json'
import blanketOrder from './po_KF-PO-0119.json'
import policy from './policy.json'
import policyPreview from './policy_preview_S12.json'
import orders from './purchase_orders.json'
import queue from './queue.json'
import detailS01 from './run_detail_S01.json'
import detailS03 from './run_detail_S03.json'
import detailS04 from './run_detail_S04.json'
import detailS06 from './run_detail_S06.json'
import runs from './runs.json'
import stats from './stats.json'
import vendors from './vendors.json'

// JSON imports widen literal values to string. Check structure here and validate
// the values against the contract in the fixture tests.
type JsonShape<T> = T extends string ? string : T extends object
  ? { [Key in keyof T]: JsonShape<T[Key]> } : T

function fixture<T>(json: JsonShape<T>): T {
  return json as T
}

export const fixtures = {
  health: fixture<Schemas['HealthResponse']>(health),
  inbox: fixture<Schemas['DemoInboxItem'][]>(inbox),
  orders: fixture<Schemas['PurchaseOrderOut'][]>(orders),
  blanketOrder: fixture<Schemas['PurchaseOrderDetail']>(blanketOrder),
  policy: fixture<Schemas['PolicyResponse']>(policy),
  policyPreview: fixture<Schemas['PolicyPreviewResponse']>(policyPreview),
  queue: fixture<Schemas['QueueResponse']>(queue),
  runs: fixture<Schemas['RunList']>(runs),
  stats: fixture<Schemas['StatsResponse']>(stats),
  vendors: fixture<Schemas['VendorOut'][]>(vendors),
  details: {
    S01: fixture<Schemas['RunDetail']>(detailS01),
    S03: fixture<Schemas['RunDetail']>(detailS03),
    S04: fixture<Schemas['RunDetail']>(detailS04),
    S06: fixture<Schemas['RunDetail']>(detailS06),
  } satisfies Record<string, Schemas['RunDetail']>,
  events: {
    S01: fixture<Schemas['RunEvent'][]>(eventsS01),
    S04: fixture<Schemas['RunEvent'][]>(eventsS04),
    S06: fixture<Schemas['RunEvent'][]>(eventsS06),
  } satisfies Record<string, Schemas['RunEvent'][]>,
}
