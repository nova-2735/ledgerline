import { inboxTags } from '../inboxTags'
import { fixtures } from '@/mocks/fixtures'

it('labels business exceptions and removes internal routing tags', () => {
  const example = { ...fixtures.inbox[0], tags: ['digital', 'missing-field', 'happy-path', 'return-to-vendor'] }
  expect(inboxTags(example)).toEqual(['Missing invoice no.', 'Digital'])
  expect(inboxTags({ ...example, tags: ['vendor-master','blocked'] })).toEqual(['Blocked vendor'])
})
