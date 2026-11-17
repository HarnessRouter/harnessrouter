import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/app-ui', timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:4175', headless: true },
  projects: [{ name: 'chromium' }, { name: 'edge', use: { channel: 'msedge' } }],
  webServer: { command: 'npx vite --host 127.0.0.1 --port 4175 --strictPort', url: 'http://127.0.0.1:4175', reuseExistingServer: false },
  reporter: 'list', outputDir: './test-results/app',
});
