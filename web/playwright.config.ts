import { defineConfig } from 'playwright/test';

const API_PORT = 3999;
const WEB_PORT = 4173;

export default defineConfig({
  testDir: './tests/smoke',
  timeout: 30_000,
  fullyParallel: true,
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`
  },
  webServer: [
    {
      command: `node --experimental-strip-types ./tests/smoke/fixture-backend.ts`,
      url: `http://127.0.0.1:${API_PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 30_000
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT}`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        CIVIBUS_API_BASE_URL: `http://127.0.0.1:${API_PORT}`,
        PUBLIC_ORIGIN: `http://127.0.0.1:${WEB_PORT}`
      }
    }
  ]
});
