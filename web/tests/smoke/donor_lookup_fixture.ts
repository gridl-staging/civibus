// @ts-expect-error Smoke fixtures run under Node ESM and import the TS module directly.
import { runSmokeSeedCommand, runSmokeSeedSql, type SmokeSeedCleanupCallback } from "./smoke_seed_helpers.ts";
import type { DonorSearchRecipient } from "$lib/donors/contract";

const fixtureConstants =
  (await import(new URL("./fixtures.ts", import.meta.url).href)) as typeof import("./fixtures");

const {
  SMOKE_DONOR_LOOKUP_QUERY,
  SMOKE_DONOR_LOOKUP_RECIPIENT_NAME,
  SMOKE_DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME,
  SMOKE_DONOR_LOOKUP_SEED_EMPLOYER,
  SMOKE_DONOR_LOOKUP_SEED_PERSON_ID,
  SMOKE_DONOR_LOOKUP_SEED_ZIP5
} = fixtureConstants;

export const SMOKE_DONOR_LOOKUP_SECOND_CONTRIBUTOR_NAME = "JANE SMITH PAGE TWO";
export const SMOKE_DONOR_LOOKUP_PAGINATION_EDIT_QUERY = "Unsubmitted Jones";
export const SMOKE_DONOR_LOOKUP_SECOND_PAGE_RESULT_COUNT = "Showing donors 2-2.";
export const SMOKE_DONOR_LOOKUP_COMBINED_COUNT_LABEL = "2 records combined";
export const SMOKE_DONOR_LOOKUP_CONFIDENCE_LABEL = "match";
export const SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_A = "JANE SMITH DURHAM";
export const SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_B = "JANE A SMITH";
export const SMOKE_DONOR_LOOKUP_COMBINED_EMPLOYER_A = "Civibus Labs";
export const SMOKE_DONOR_LOOKUP_COMBINED_CITY_A = "Durham";
export const SMOKE_DONOR_LOOKUP_COMBINED_CITY_B = "Raleigh";
export const SMOKE_DONOR_LOOKUP_NOT_COMBINED_CONTRIBUTOR = "JANET SMYTHE NOT COMBINED";

/**
 * Removes the donor-search fixture rows and rebuilds the donor rollup.
 *
 * The live lane runs every spec against one shared database, so a fixture that
 * seeds rows and never removes them is not local to its own journey: this one
 * adds three current federal officeholders and six candidates, which made
 * `/congress` report 5 members instead of 3 and the candidate and committee
 * lists report `Showing 1-6` instead of `Showing 1-1` for whichever specs
 * happened to run afterwards. Deleting the rows on teardown is what keeps those
 * whole-database assertions about the browser-smoke seed and nothing else.
 *
 * The rebuild also restores a valid rollup provenance fingerprint, which is why
 * this single call replaces the narrower fingerprint-only restore it grew from:
 * the journey deliberately corrupts that fingerprint mid-test to prove the
 * unavailable state renders, and a rebuild is a superset of undoing it.
 */
async function cleanUpLiveDonorLookupSmoke(): Promise<void> {
  await runSmokeSeedCommand("uv", [
    "run",
    "--directory",
    "..",
    "--extra",
    "dev",
    "python",
    "-m",
    "test_support.donor_search_fixture",
    "--cleanup"
  ]);
}

export async function seedLiveDonorLookupSmoke(): Promise<SmokeSeedCleanupCallback> {
  await runSmokeSeedCommand("uv", [
    "run",
    "--directory",
    "..",
    "--extra",
    "dev",
    "python",
    "-m",
    "test_support.donor_search_fixture"
  ]);
  return cleanUpLiveDonorLookupSmoke;
}

export async function makeLiveDonorLookupFingerprintIncompatible(): Promise<void> {
  await runSmokeSeedSql(`
    UPDATE cf.donor_search_rollup_provenance
    SET donor_key_fingerprint = donor_key_fingerprint || '.smoke_mismatch'
    WHERE singleton;
  `);
}

function parseOptionalNonNegativeInt(value: string | null): number | null {
  if (value === null) {
    return null;
  }

  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) {
    return null;
  }

  return parsed;
}

type FixtureJsonObject = Record<string, unknown>;

function buildFixtureSource(params: { key: string; recordUrl: string }): FixtureJsonObject {
  return {
    domain: "campaign_finance",
    jurisdiction: "federal/fec",
    data_source_name: "Campaign Finance API Source donor-search-fixture",
    data_source_url: "https://www.fec.gov/data/receipts/individual-contributions/",
    source_record_key: params.key,
    record_url: params.recordUrl,
    pull_date: "2026-07-09T12:00:00Z"
  };
}

function buildUnderlyingRecord(params: {
  donorIdentityId: string;
  contributorName: string;
  employer: string | null;
  occupation: string | null;
  city: string | null;
  state: string | null;
  zip5: string | null;
  sourceKey: string;
  recordUrl: string;
}): FixtureJsonObject {
  return {
    donor_identity_id: params.donorIdentityId,
    contributor_name: params.contributorName,
    contributor_employer: params.employer,
    contributor_occupation: params.occupation,
    contributor_city: params.city,
    contributor_state: params.state,
    normalized_zip5: params.zip5,
    sources: [
      buildFixtureSource({
        key: params.sourceKey,
        recordUrl: params.recordUrl
      })
    ]
  };
}

function buildNotCombinedCandidate(params: {
  donorIdentityId: string;
  contributorName: string;
  employer: string | null;
  occupation: string | null;
  city: string | null;
  state: string | null;
  zip5: string | null;
  sourceKey: string;
  recordUrl: string;
}): FixtureJsonObject {
  return {
    ...buildUnderlyingRecord(params),
    confidence_band: "possible_match"
  };
}

function buildResolvedIdentityEvidence(params: { id: string; unsafeRecordUrls: boolean }): {
  donorIdentityId: string;
  confidenceBand: "match" | "probable_match";
  underlyingRecords: FixtureJsonObject[];
  notCombinedCandidates: FixtureJsonObject[];
} {
  const donorIdentityId = `${params.id}-identity`;
  const combinedRecordUrl = params.unsafeRecordUrls
    ? "javascript:alert('combined-unsafe')"
    : "https://docquery.fec.gov/cgi-bin/fecimg/?202407159684778901";
  const candidateRecordUrl = params.unsafeRecordUrls
    ? "javascript:alert('candidate-unsafe')"
    : "https://docquery.fec.gov/cgi-bin/fecimg/?202407159684778903";

  return {
    donorIdentityId,
    confidenceBand: params.unsafeRecordUrls ? "probable_match" : "match",
    underlyingRecords: [
      buildUnderlyingRecord({
        donorIdentityId,
        contributorName: params.unsafeRecordUrls
          ? "UNSAFE COMBINED DISCLOSURE"
          : SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_A,
        employer: params.unsafeRecordUrls ? "Unsafe Employer" : SMOKE_DONOR_LOOKUP_COMBINED_EMPLOYER_A,
        occupation: "Engineer",
        city: params.unsafeRecordUrls ? "Greensboro" : SMOKE_DONOR_LOOKUP_COMBINED_CITY_A,
        state: "NC",
        zip5: SMOKE_DONOR_LOOKUP_SEED_ZIP5,
        sourceKey: `${params.id}:combined-1`,
        recordUrl: combinedRecordUrl
      }),
      buildUnderlyingRecord({
        donorIdentityId,
        contributorName: params.unsafeRecordUrls
          ? "UNSAFE COMBINED DISCLOSURE TWO"
          : SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_B,
        employer: "Open Records Works",
        occupation: "Architect",
        city: params.unsafeRecordUrls ? "Charlotte" : SMOKE_DONOR_LOOKUP_COMBINED_CITY_B,
        state: "NC",
        zip5: "27601",
        sourceKey: `${params.id}:combined-2`,
        recordUrl: params.unsafeRecordUrls
          ? "javascript:alert('combined-unsafe-two')"
          : "https://docquery.fec.gov/cgi-bin/fecimg/?202407159684778902"
      })
    ],
    notCombinedCandidates: [
      buildNotCombinedCandidate({
        donorIdentityId: `${donorIdentityId}-candidate`,
        contributorName: params.unsafeRecordUrls
          ? "UNSAFE POSSIBLE MATCH"
          : SMOKE_DONOR_LOOKUP_NOT_COMBINED_CONTRIBUTOR,
        employer: "Separate Donor Works",
        occupation: "Attorney",
        city: "Cary",
        state: "NC",
        zip5: "27511",
        sourceKey: `${params.id}:possible-match`,
        recordUrl: candidateRecordUrl
      })
    ]
  };
}

function buildDonorSearchResult(params: {
  id: string;
  contributorName: string;
  totalAmount: string;
  unsafeRecordUrls?: boolean;
}): unknown {
  const identityEvidence = buildResolvedIdentityEvidence({
    id: params.id,
    unsafeRecordUrls: params.unsafeRecordUrls ?? false
  });

  return {
    id: params.id,
    donor_identity_id: identityEvidence.donorIdentityId,
    contributor_name: params.contributorName,
    contributor_employer: SMOKE_DONOR_LOOKUP_SEED_EMPLOYER,
    contributor_occupation: "Engineer",
    contributor_city: "Durham",
    contributor_state: "NC",
    normalized_zip5: SMOKE_DONOR_LOOKUP_SEED_ZIP5,
    total_amount: params.totalAmount,
    transaction_count: identityEvidence.underlyingRecords.length,
    latest_transaction_date: "2024-07-15",
    combined_record_count: identityEvidence.underlyingRecords.length,
    confidence_band: identityEvidence.confidenceBand,
    recipients: [
      {
        person_id: SMOKE_DONOR_LOOKUP_SEED_PERSON_ID,
        candidate_id: "72000000-0000-0000-0000-000000000014",
        fec_candidate_id: "H0NC01001",
        candidate_name: SMOKE_DONOR_LOOKUP_RECIPIENT_NAME,
        committee_id: "72000000-0000-0000-0000-000000000015",
        fec_committee_id: "C72000001",
        committee_name: "Alpha Officeholder Committee",
        total_amount: params.totalAmount,
        transaction_count: 1,
        identity_is_safe: true
      } satisfies DonorSearchRecipient
    ],
    sources: [
      buildFixtureSource({
        key: `${params.id}:source`,
        recordUrl: "https://docquery.fec.gov/cgi-bin/fecimg/?202407159684778900"
      })
    ],
    underlying_records: identityEvidence.underlyingRecords,
    not_combined_candidates: identityEvidence.notCombinedCandidates
  };
}

export function buildDonorSearchResponse(url: URL): unknown | null {
  if (url.pathname !== "/v1/donors/search") {
    return null;
  }

  const query = url.searchParams.get("q") ?? "";
  const by = url.searchParams.get("by") ?? "name";
  const limit = parseOptionalNonNegativeInt(url.searchParams.get("limit")) ?? 20;
  const offset = parseOptionalNonNegativeInt(url.searchParams.get("offset")) ?? 0;
  const allResults =
    query === SMOKE_DONOR_LOOKUP_QUERY && by === "name"
      ? [
          buildDonorSearchResult({
            id: "72000000-0000-0000-0000-000000000101",
            contributorName: SMOKE_DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME,
            totalAmount: "500.00"
          }),
          buildDonorSearchResult({
            id: "72000000-0000-0000-0000-000000000102",
            contributorName: SMOKE_DONOR_LOOKUP_SECOND_CONTRIBUTOR_NAME,
            totalAmount: "250.00",
            unsafeRecordUrls: true
          })
        ]
      : [];

  return {
    query,
    by,
    limit,
    offset,
    rollup_completed_at: "2026-07-17T12:00:00Z",
    results: allResults.slice(offset, offset + limit)
  };
}
