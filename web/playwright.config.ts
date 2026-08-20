import { defineConfig, devices } from 'playwright/test';
import { resolveSmokeApiPort, resolveSmokeWebPort } from "./src/lib/server/api/smoke-port";
import {
  resolveSmokeExecutionMode,
  specsExcludedFromMode
} from "./tests/smoke/execution-contract";

const API_PORT = resolveSmokeApiPort(process.env);
const WEB_PORT = resolveSmokeWebPort(process.env);
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

const EXECUTION_MODE = resolveSmokeExecutionMode(process.env);

export default defineConfig({
  testDir: './tests/smoke',
  // Routing, not skipping. tests/smoke/execution-contract.json declares which
  // backend each spec's oracle is written against; a spec that cannot hold in
  // this mode is not collected, so the run neither fails on it nor reports a
  // skip that hides which lane owns it. The declaration carries the reason and
  // the owning lane per spec, and tests/ci/test_ci_workflow_contract.py refuses
  // an undeclared spec, an unexplained exclusion, or a lane with no nightly job.
  testIgnore: specsExcludedFromMode(EXECUTION_MODE),
  timeout: 30_000,
  fullyParallel: true,
  // Production smoke runs read-only against ONE small live Fly instance. Running
  // it fully parallel makes the gate a load test against itself: a burst of
  // concurrent page loads (the committee page alone takes ~6.5s) drives heavy
  // surfaces past their 20s budget, so tests fail for contention the deploy did
  // not cause. Local live-API smoke also needs one worker because several specs
  // own temporary DB seed/cleanup lifecycles; parallel workers can make those
  // fixtures visible to unrelated journeys. Retries remain production-only and
  // absorb only rare single-request transients of a live service. Local fixture
  // mode is unaffected (undefined workers = full parallelism against the
  // throwaway fixture backend).
  workers: isProductionSmokeMode || USE_LIVE_API ? 1 : undefined,
  retries: isProductionSmokeMode ? 2 : 0,
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"]
      }
    }
  ],
  expect: {
    toHaveScreenshot: {
      pathTemplate:
        "{snapshotDir}/{testFileDir}/{testFileName}-snapshots/{arg}{-projectName}{ext}"
    }
  },
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
