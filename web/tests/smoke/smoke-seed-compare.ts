/**
 * Compare exact-value smoke seed/cleanup owner.
 *
 * Seeds the two deterministic `/compare` officeholders (people, committees, candidates,
 * links) with official totals and self-funding columns, and provides the fail-closed API
 * readiness probe the public seam runs before the compare proof asserts rendered values.
 */
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { SMOKE_COMPARE_LIVE_INPUTS } from "./fixtures.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { jsonbLiteral, moneyLiteral, sqlLiteral, sqlUuid } from "./smoke_seed_helpers.ts";

const SMOKE_COMPARE_DATA_SOURCE_ID = "93000000-0000-4000-8000-000000000401";
const SMOKE_COMPARE_SOURCE_RECORD_ID = "93000000-0000-4000-8000-000000000402";

function compareCandidateOfficeSql(fecCandidateId: string): {
  officeSql: string;
  districtSql: string;
} {
  const office = fecCandidateId[0];
  if (office !== "H" && office !== "S") {
    throw new Error(
      `Compare smoke fecCandidateId must start with H or S, received: ${fecCandidateId}`
    );
  }
  return {
    officeSql: sqlLiteral(office),
    districtSql: office === "H" ? sqlLiteral("01") : "NULL"
  };
}

export function buildCompareSmokeCleanupSql(): string {
  const personIds = SMOKE_COMPARE_LIVE_INPUTS.map(({ personId }) => sqlUuid(personId, "compare personId")).join(", ");
  const candidateIds = SMOKE_COMPARE_LIVE_INPUTS.map(({ candidateId }) => sqlUuid(candidateId, "compare candidateId")).join(", ");
  const committeeIds = SMOKE_COMPARE_LIVE_INPUTS.map(({ committeeId }) => sqlUuid(committeeId, "compare committeeId")).join(", ");
  const linkIds = SMOKE_COMPARE_LIVE_INPUTS.map(({ linkId }) => sqlUuid(linkId, "compare linkId")).join(", ");
  return `BEGIN;
DELETE FROM cf.candidate_committee_link WHERE id IN (${linkIds});
DELETE FROM cf.candidate WHERE id IN (${candidateIds});
DELETE FROM cf.committee WHERE id IN (${committeeIds});
DELETE FROM core.person WHERE id IN (${personIds});
DELETE FROM core.source_record WHERE id = ${sqlUuid(SMOKE_COMPARE_SOURCE_RECORD_ID, "SMOKE_COMPARE_SOURCE_RECORD_ID")};
DELETE FROM core.data_source WHERE id = ${sqlUuid(SMOKE_COMPARE_DATA_SOURCE_ID, "SMOKE_COMPARE_DATA_SOURCE_ID")};
COMMIT;`;
}

export function buildCompareSmokeSeedSql(): string {
  const peopleRows = SMOKE_COMPARE_LIVE_INPUTS.map((input) => {
    const nameParts = input.name.split(" ");
    return `(${sqlUuid(input.personId, "compare personId")}, ${sqlLiteral(input.name)}, ${sqlLiteral(nameParts[0])}, ${sqlLiteral(nameParts.at(-1) ?? nameParts[0])}, ${jsonbLiteral({ fec_candidate_id: input.fecCandidateId })})`;
  }).join(",\n  ");
  const committeeRows = SMOKE_COMPARE_LIVE_INPUTS.map((input) => `(${sqlUuid(input.committeeId, "compare committeeId")}, ${sqlLiteral(input.fecCommitteeId)}, ${sqlLiteral(`${input.name} Committee`)}, ${sqlUuid(SMOKE_COMPARE_SOURCE_RECORD_ID, "SMOKE_COMPARE_SOURCE_RECORD_ID")}, 'P', 'P', 'NC')`).join(",\n  ");
  const candidateRows = SMOKE_COMPARE_LIVE_INPUTS.map((input) => {
    const { officeSql, districtSql } = compareCandidateOfficeSql(input.fecCandidateId);
    return `(${sqlUuid(input.candidateId, "compare candidateId")}, ${sqlLiteral(input.fecCandidateId)}, ${sqlLiteral(input.name)}, ${officeSql}, ${sqlUuid(input.personId, "compare personId")}, ${sqlUuid(input.committeeId, "compare committeeId")}, ${sqlUuid(SMOKE_COMPARE_SOURCE_RECORD_ID, "SMOKE_COMPARE_SOURCE_RECORD_ID")}, 'NC', ${districtSql}, 'I', ${moneyLiteral(input.totalRaised)}, ${moneyLiteral(input.totalSpent)}, ${input.cashOnHand === null ? "NULL" : moneyLiteral(input.cashOnHand)}, ${moneyLiteral(input.candidateContrib)}, ${moneyLiteral(input.candidateLoans)}, ${moneyLiteral(input.candidateLoanRepay)}, '2026-06-30')`;
  }).join(",\n  ");
  const linkRows = SMOKE_COMPARE_LIVE_INPUTS.map((input) => `(${sqlUuid(input.linkId, "compare linkId")}, ${sqlUuid(input.candidateId, "compare candidateId")}, ${sqlUuid(input.committeeId, "compare committeeId")}, 'P', 2026, 2026, '[2025-01-01,2100-01-01)'::daterange, ${sqlUuid(SMOKE_COMPARE_SOURCE_RECORD_ID, "SMOKE_COMPARE_SOURCE_RECORD_ID")})`).join(",\n  ");
  return `${buildCompareSmokeCleanupSql()}
BEGIN;
INSERT INTO core.data_source (id, domain, jurisdiction, name, source_url, source_format, license, update_frequency)
VALUES (${sqlUuid(SMOKE_COMPARE_DATA_SOURCE_ID, "SMOKE_COMPARE_DATA_SOURCE_ID")}, 'campaign_finance', 'federal/fec', 'Compare exact-value smoke source', 'https://example.org/compare-smoke/fec', 'csv', 'public_domain', 'weekly');
INSERT INTO core.source_record (id, data_source_id, source_record_key, source_url, raw_fields, pull_date, record_hash)
VALUES (${sqlUuid(SMOKE_COMPARE_SOURCE_RECORD_ID, "SMOKE_COMPARE_SOURCE_RECORD_ID")}, ${sqlUuid(SMOKE_COMPARE_DATA_SOURCE_ID, "SMOKE_COMPARE_DATA_SOURCE_ID")}, 'smoke-compare-exact-values', 'https://example.org/compare-smoke/fec-summary', '{}'::jsonb, '2026-07-31T12:00:00Z', 'smoke-compare-exact-values-hash');
INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers) VALUES
  ${peopleRows};
INSERT INTO cf.committee (id, fec_committee_id, name, source_record_id, committee_type, committee_designation, state) VALUES
  ${committeeRows};
INSERT INTO cf.candidate (id, fec_candidate_id, name, office, person_id, principal_committee_id, source_record_id, state, district, incumbent_challenge, total_receipts, total_disbursements, cash_on_hand, candidate_contrib, candidate_loans, candidate_loan_repay, summary_coverage_end_date) VALUES
  ${candidateRows};
INSERT INTO cf.candidate_committee_link (id, candidate_id, committee_id, designation, candidate_election_year, fec_election_year, valid_period, source_record_id) VALUES
  ${linkRows};
COMMIT;`;
}

export async function assertCompareSmokeApiReady(): Promise<void> {
  const baseUrl = process.env.SMOKE_LIVE_API_BASE_URL?.trim() || "http://127.0.0.1:8000";
  for (const input of SMOKE_COMPARE_LIVE_INPUTS) {
    const [personResponse, summaryResponse] = await Promise.all([fetch(`${baseUrl}/v1/person/${input.personId}`), fetch(`${baseUrl}/v1/candidates/${input.candidateId}/summary?cycle=2026`)]);
    if (!personResponse.ok || !summaryResponse.ok) {
      throw new Error(`Compare smoke API readiness failed for ${input.personId}: person=${personResponse.status}, summary=${summaryResponse.status}`);
    }
    const person = (await personResponse.json()) as {
      canonical_name?: unknown;
    };
    if (person.canonical_name !== input.name) {
      throw new Error(`Compare smoke API readiness returned the wrong person for ${input.personId}`);
    }
  }
}
