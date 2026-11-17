import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/integration-ui', timeout: 45000,
  use: { baseURL: 'http://127.0.0.1:4176', headless: true, viewport: { width: 1440, height: 900 } },
  projects: [{ name: 'chromium' }, { name: 'edge', use: { channel: 'msedge' } }],
  webServer: [
    { command: 'python ../hexa-api/tests/serve_e2e.py', url: 'http://127.0.0.1:4012/healthz', reuseExistingServer: false },
    { command: 'npx vite --host 127.0.0.1 --port 4176 --strictPort', url: 'http://127.0.0.1:4176', env: { HEXA_API_PROXY: 'http://127.0.0.1:4012' }, reuseExistingServer: false },
  ], reporter: 'list', outputDir: './test-results/integration',
});
