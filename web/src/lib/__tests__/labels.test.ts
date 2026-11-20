import openapi from '../../../../backend/openapi.json'
import { outcomes, reasons, routes, stages } from '../labels'

const schema = openapi.components.schemas

it.each([
  ['StageName', stages], ['ReasonCode', reasons], ['Route', routes], ['Outcome', outcomes],
] as const)('has a plain label for every %s', (name, labels) => {
  expect(Object.keys(labels).sort()).toEqual([...schema[name].enum].sort())
  expect(Object.values(labels).every(label => label.trim().length > 0)).toBe(true)
})
