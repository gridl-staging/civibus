/**
 * TS wrapper for the dedicated person-resilience specimen (civibus-e7v).
 *
 * Paired with test_support/person_resilience_fixture.py — the Python module is
 * the single owner of the specimen rows and of the ga8-class poison (a
 * column-legal NaN in cf.candidate.total_receipts that the response contract
 * rejects). This wrapper only shells into it, mirroring the
 * donor_lookup_fixture.ts seed/poison/restore shape.
 *
 * The constants are canonical literals mirrored from the Python module (TS
 * cannot import it); tests/integration/test_person_resilience_fixture.py pins
 * the Python side, and the journey's healthy-page assertions pin these.
 */
// @ts-expect-error Smoke fixtures run under Node ESM and import the TS module directly.
import { runSmokeSeedCommand, type SmokeSeedCleanupCallback } from "./smoke_seed_helpers.ts";

// Mirrors SMOKE_RESILIENCE_PERSON_ID in test_support/person_resilience_fixture.py.
export const SMOKE_RESILIENCE_PERSON_ID = "e5111111-1111-4111-8111-111111111111";
// Mirrors SMOKE_RESILIENCE_PERSON_CANONICAL_NAME.
export const SMOKE_RESILIENCE_PERSON_NAME = "Riley Resilience";
// Rendered form of SMOKE_RESILIENCE_TOTAL_RECEIPTS ("400.00") — the seed owns the number.
export const SMOKE_RESILIENCE_TOTAL_RAISED = "$400.00";

async function runPersonResilienceFixture(args: string[]): Promise<void> {
  await runSmokeSeedCommand("uv", [
    "run",
    "--directory",
    "..",
    "--extra",
    "dev",
    "python",
    "-m",
    "test_support.person_resilience_fixture",
    ...args
  ]);
}

/** Idempotently (re)seed the dedicated specimen; returns the row-removing cleanup. */
export async function seedLivePersonResilienceSmoke(): Promise<SmokeSeedCleanupCallback> {
  await runPersonResilienceFixture([]);
  return cleanUpLivePersonResilienceSmoke;
}

/** Write the response-contract-illegal NaN into the specimen's official total. */
export async function poisonLivePersonResilienceCandidate(): Promise<void> {
  await runPersonResilienceFixture(["--poison"]);
}

/** Undo the poison, restoring the seeded official total. */
export async function restoreLivePersonResilienceCandidate(): Promise<void> {
  await runPersonResilienceFixture(["--restore"]);
}

/**
 * Remove the specimen entirely. The specimen is a current federal
 * officeholder, so leaving it seeded would shift whole-database assertions
 * (the /congress member count, browse-list "Showing 1–N" labels) for every
 * spec that runs after this one in the shared live database.
 */
export async function cleanUpLivePersonResilienceSmoke(): Promise<void> {
  await runPersonResilienceFixture(["--cleanup"]);
}
