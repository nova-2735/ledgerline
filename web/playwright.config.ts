import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const apiPort = Number(process.env.E2E_API_PORT ?? 8000)
const webPort = Number(process.env.E2E_WEB_PORT ?? 5173)
const apiURL = 'http://127.0.0.1:' + apiPort
const baseURL = 'http://127.0.0.1:' + webPort
const dataDir = process.env.LEDGERLINE_E2E_DATA
if (!dataDir) throw new Error('Start the isolated test stack with make e2e.')

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  outputDir: '../reports/playwright',
  workers: 1,
  timeout: 60000,
  expect: { timeout: 15000 },
  use: {
    baseURL, viewport: { width: 1440, height: 900 },
    channel: process.env.PLAYWRIGHT_CHANNEL || (process.platform === 'win32' ? 'msedge' : 'chromium'),
  },
  webServer: [
    {
      command: 'uv run python -m app.demo.seed && uv run uvicorn app.main:app --host 127.0.0.1 --port ' + apiPort,
      cwd: fileURLToPath(new URL('../backend/', import.meta.url)), url: apiURL + '/api/health',
      timeout: 120000, reuseExistingServer: false,
      env: {
        DATA_DIR: dataDir, DATABASE_URL: 'sqlite:///' + dataDir.replaceAll('\\', '/') + '/ledgerline.db',
        APP_ENV: 'test', APP_TODAY: '2026-11-20', LLM_PROVIDER: 'fake', ALLOW_FAKE_LLM: '1',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port ' + webPort + ' --strictPort',
      url: baseURL, reuseExistingServer: false, env: { VITE_DEV_API_TARGET: apiURL, VITE_API_BASE: '/api', VITE_USE_MOCKS: '0' },
    },
  ],
})
