/**
 * Public setup seam for live smoke seeding.
 *
 * Dispatches each scenario to its focused SQL-fragment owner and keeps the three
 * long-lived exports (`buildCongressSmokeSeedSql`, `buildCongressSmokeCleanupSql`,
 * `seedLiveCongressDirectorySmoke`) stable for the smoke specs and fixtures.ts. Scenario
 * detail lives in the ./smoke-seed-congress-* and ./smoke-seed-compare owners; the search
 * officeholder entry point is re-exported from ./smoke-seed-search.
 */
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { runSmokeSeedSql, type SmokeSeedCleanupCallback } from "./smoke_seed_helpers.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { congressPersonSmokeFixture, type CongressSmokeScenario } from "./smoke-seed-congress-fixture.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { buildCongressPersonGraphMergeSql, buildCongressPersonSmokeCleanupSql, buildCongressPersonSmokeSeedSql } from "./smoke-seed-congress-person.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { assertCompareSmokeApiReady, buildCompareSmokeCleanupSql, buildCompareSmokeSeedSql } from "./smoke-seed-compare.ts";

// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
export { seedLiveSearchOfficeholderSmoke } from "./smoke-seed-search.ts";

export function buildCongressSmokeCleanupSql(scenario: CongressSmokeScenario = "directory"): string {
  if (scenario === "compare") return buildCompareSmokeCleanupSql();
  return buildCongressPersonSmokeCleanupSql(congressPersonSmokeFixture(scenario));
}

export function buildCongressSmokeSeedSql(scenario: CongressSmokeScenario = "directory"): string {
  if (scenario === "compare") return buildCompareSmokeSeedSql();
  return buildCongressPersonSmokeSeedSql(congressPersonSmokeFixture(scenario));
}

async function cleanupAfterSetupFailure(cleanupSql: string, originalError: unknown, context: string): Promise<never> {
  try {
    await runSmokeSeedSql(cleanupSql);
  } catch (cleanupError) {
    throw new AggregateError([originalError, cleanupError], `${context}; cleanup failed too.`);
  }
  throw originalError;
}

async function seedLiveCompareSmoke(): Promise<SmokeSeedCleanupCallback> {
  const cleanupSql = buildCompareSmokeCleanupSql();
  await runSmokeSeedSql(buildCompareSmokeSeedSql());
  try {
    await assertCompareSmokeApiReady();
  } catch (error) {
    return cleanupAfterSetupFailure(cleanupSql, error, "Compare smoke API readiness failed");
  }
  return async () => {
    await runSmokeSeedSql(cleanupSql);
  };
}

export async function seedLiveCongressDirectorySmoke(scenario: CongressSmokeScenario = "directory"): Promise<SmokeSeedCleanupCallback> {
  if (scenario === "compare") {
    return seedLiveCompareSmoke();
  }
  const fixture = congressPersonSmokeFixture(scenario);
  const cleanupSql = buildCongressPersonSmokeCleanupSql(fixture);
  await runSmokeSeedSql(buildCongressPersonSmokeSeedSql(fixture));
  try {
    await runSmokeSeedSql(buildCongressPersonGraphMergeSql(fixture));
  } catch (error) {
    return cleanupAfterSetupFailure(cleanupSql, error, `Congress smoke graph merge failed for ${scenario}`);
  }
  return async () => {
    await runSmokeSeedSql(cleanupSql);
  };
}
