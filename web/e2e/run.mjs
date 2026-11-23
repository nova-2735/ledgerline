import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const data = await mkdtemp(join(tmpdir(), 'ledgerline-e2e-'))
try {
  const result = spawnSync(process.execPath, [require.resolve('@playwright/test/cli'), 'test', ...process.argv.slice(2)], {
    stdio: 'inherit', env: { ...process.env, LEDGERLINE_E2E_DATA: data },
  })
  if (result.error) throw result.error
  process.exitCode = result.status ?? 1
} finally {
  await rm(data, { recursive: true, force: true, maxRetries: 4 })
}
