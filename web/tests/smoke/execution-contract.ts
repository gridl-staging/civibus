/**
 * Smoke-suite execution contract: which spec runs against which backend.
 *
 * The declaration itself lives in ./execution-contract.json so the Playwright
 * config (TypeScript) and the CI contract tests (Python) read one file rather
 * than two copies that can drift. This module is the only place that turns the
 * declaration into routing; playwright.config.ts consumes `specsExcludedFromMode`
 * as its `testIgnore`, so a spec is not collected at all in a mode it does not
 * declare. tests/ci/test_ci_workflow_contract.py fails when a spec is undeclared,
 * when an entry has no written reason, when a mode has no spec, when this routing
 * stops being wired into the config, or when a local lane has no nightly job.
 *
 * Read with a plain readFileSync rather than a JSON import: this module is loaded
 * by Playwright's config loader and by node --experimental-strip-types, and JSON
 * import attributes are not spelled the same way in both.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type SmokeExecutionMode = "fixture" | "live" | "production";

type SmokeExecutionContractEntry = {
  modes: SmokeExecutionMode[];
  reason: string;
};

const CONTRACT_PATH = resolve(dirname(fileURLToPath(import.meta.url)), "execution-contract.json");

const CONTRACT: Record<string, SmokeExecutionContractEntry> = JSON.parse(
  readFileSync(CONTRACT_PATH, "utf8")
).specs;

/**
 * The mode the current process is running in.
 *
 * SMOKE_MODE=production wins because it targets a deployed origin and the live
 * flag is meaningless there. Otherwise SMOKE_USE_LIVE_API=1 selects the seeded
 * database and the default is the Node fixture backend, matching the precedence
 * playwright.config.ts already applies to its webServer list.
 */
export function resolveSmokeExecutionMode(
  environment: Record<string, string | undefined>
): SmokeExecutionMode {
  if ((environment.SMOKE_MODE ?? "local") === "production") {
    return "production";
  }
  return environment.SMOKE_USE_LIVE_API === "1" ? "live" : "fixture";
}

/**
 * Glob patterns for every spec the contract excludes from `mode`.
 *
 * Playwright matches testIgnore against the absolute file path, so each entry is
 * anchored with `**` on the smoke directory's unique basenames. An unknown
 * filename throws rather than defaulting to "run it": a spec that slipped past
 * the contract must fail loudly here, not quietly execute in every lane, which is
 * the state that produced 38 unrunnable live-lane failures.
 */
export function specsExcludedFromMode(mode: SmokeExecutionMode): string[] {
  return Object.entries(CONTRACT)
    .filter(([, entry]) => !entry.modes.includes(mode))
    .map(([specName]) => `**/${specName}`);
}

/** Spec filenames the contract allows in `mode`, for diagnostics and tests. */
export function specsForMode(mode: SmokeExecutionMode): string[] {
  return Object.entries(CONTRACT)
    .filter(([, entry]) => entry.modes.includes(mode))
    .map(([specName]) => specName)
    .sort();
}
