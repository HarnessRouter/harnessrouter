import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 120000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: './test-results/e2e-report', open: 'never' }]],
  outputDir: './test-results/e2e',
  use: {
    baseURL: 'http://127.0.0.1:4020',
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', testIgnore: /cross-browser\.spec\.ts/, use: { browserName: 'chromium' } },
    { name: 'edge', testMatch: /cross-browser\.spec\.ts/, use: { channel: 'msedge', viewport: { width: 1280, height: 800 } } },
  ],
  webServer: [
    {
      command: 'python ../hexa-api/tests/serve_e2e.py',
      url: 'http://127.0.0.1:4022/healthz',
      reuseExistingServer: false,
      timeout: 60000,
      env: { HEXA_E2E_GATEWAY_PORT: '4021', HEXA_E2E_APP_PORT: '4022' },
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 4020 --strictPort',
      url: 'http://127.0.0.1:4020',
      reuseExistingServer: false,
      timeout: 60000,
      env: { HEXA_API_PROXY: 'http://127.0.0.1:4022' },
    },
  ],
});
