import { defineConfig } from 'playwright/test';
import { resolveSmokeApiPort } from "./src/lib/server/api/smoke-port.ts";

const API_PORT = resolveSmokeApiPort(process.env);
const WEB_PORT = 4173;
const USE_LIVE_API = process.env.SMOKE_USE_LIVE_API === "1";
const smokeMode = process.env.SMOKE_MODE ?? "local";
const isProductionSmokeMode = smokeMode === "production";
const baseURL = process.env.SMOKE_BASE_URL ?? `http://127.0.0.1:${WEB_PORT}`;
const apiBaseUrl = USE_LIVE_API
  ? (process.env.SMOKE_LIVE_API_BASE_URL ?? "http://127.0.0.1:8000")
  : `http://127.0.0.1:${API_PORT}`;

const backendServer = USE_LIVE_API
  ? []
  : [
      {
        command: `node --experimental-strip-types ./tests/smoke/fixture-backend.ts`,
        url: `http://127.0.0.1:${API_PORT}/healthz`,
        reuseExistingServer: false,
        timeout: 30_000
      }
    ];

export default defineConfig({
  testDir: './tests/smoke',
  timeout: 30_000,
  fullyParallel: true,
  use: {
    baseURL
  },
  webServer: isProductionSmokeMode
    ? undefined
    : [
        ...backendServer,
        {
          command: `npm run build && npm run preview -- --host 127.0.0.1 --port ${WEB_PORT}`,
          url: `http://127.0.0.1:${WEB_PORT}`,
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            CIVIBUS_API_BASE_URL: apiBaseUrl,
            PUBLIC_ORIGIN: `http://127.0.0.1:${WEB_PORT}`
          }
        }
      ]
});
