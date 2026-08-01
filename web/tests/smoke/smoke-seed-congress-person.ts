/**
 * Congress person smoke seed/cleanup SQL owner.
 *
 * Owns the full seed and symmetric cleanup for the directory / charts / finance person
 * scenarios. The public setup seam (./smoke-seed-sql.ts) dispatches person scenarios
 * here after resolving a `CongressPersonSmokeFixture`. Each INSERT/DELETE group is a
 * focused fragment so no single builder exceeds the size limits and the seed reads as
 * an ordered list of table writes.
 */
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { SMOKE_CANDIDATE_NAME, SMOKE_CANDIDATE_TOTAL_RAISED, SMOKE_CANDIDATE_TOTAL_SPENT, SMOKE_CHART_LIVE_RECEIPT_INDIVIDUAL_DOLLARS, SMOKE_CHART_LIVE_RECEIPT_PAC_DOLLARS, SMOKE_CHART_LIVE_RECEIPT_TOTAL_DOLLARS, SMOKE_CHART_LIVE_SUMMARY_COVERAGE_END, SMOKE_COMMITTEE_NAME, SMOKE_CONGRESS_PORTRAIT_URL, SMOKE_FINANCE_LIVE_IE_COMMITTEE_B_NAME, SMOKE_IE_COMMITTEE_A_NAME, SMOKE_OFFICE_ID, SMOKE_PERSON_CANONICAL_NAME, SMOKE_PERSON_CASH_ON_HAND_DOLLARS, SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS, SMOKE_PERSON_TOTAL_CONTRIBUTION_DOLLARS, SMOKE_PERSON_UNITEMIZED_DOLLARS } from "./fixtures.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { cypherString, jsonbLiteral, moneyLiteral, sqlLiteral, sqlUuid } from "./smoke_seed_helpers.ts";
// Type-only import: erased at emit, so the .ts extension needs no @ts-expect-error.
import type { CongressPersonSmokeFixture } from "./smoke-seed-congress-fixture.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { buildCongressPersonIeTransactionRows, buildCongressPersonReceiptTransactionRows } from "./smoke-seed-congress-transactions.ts";

const SMOKE_SHARED_OFFICE_DATA_SOURCE_ID = "96000000-0000-4000-8000-000000000401";
const SMOKE_SHARED_OFFICE_SOURCE_RECORD_ID = "96000000-0000-4000-8000-000000000402";

function smokeSourceBaseUrl(fixture: CongressPersonSmokeFixture): string {
  return `https://example.org/${fixture.scenarioSlug}-smoke`;
}

export function buildCongressPersonSmokeCleanupSql(fixture: CongressPersonSmokeFixture): string {
  return `
${buildCongressPersonGraphDeleteSql(fixture.SMOKE_CONGRESS_PERSON_ID)}
BEGIN;
${buildCongressPersonCfCleanupDeletes(fixture)}
${buildCongressPersonCoreCleanupDeletes(fixture)}
COMMIT;
`;
}

function buildCongressPersonGraphDeleteSql(personId: string): string {
  return `LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT ag_catalog.create_graph('civibus')
WHERE NOT EXISTS (
  SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'civibus'
);
SELECT *
FROM ag_catalog.cypher('civibus', $$
  MATCH (n:Person {id: "${cypherString(personId)}"})
  DETACH DELETE n
$$) AS (v agtype);`;
}

function buildCongressPersonCfCleanupDeletes(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, SMOKE_CONGRESS_IE_SUPPORT_TRANSACTION_ID, SMOKE_CONGRESS_IE_OPPOSE_TRANSACTION_ID, SMOKE_CONGRESS_RECEIPT_JANUARY_ID, SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID, SMOKE_CONGRESS_COMMITTEE_SUMMARY_2022_ID, SMOKE_CONGRESS_COMMITTEE_SUMMARY_2024_ID, SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID, SMOKE_CONGRESS_FILING_FEC_ID, SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_FEC_ID, SMOKE_CONGRESS_RECEIPT_FILING_FEC_ID, SMOKE_CONGRESS_LINK_ID, SMOKE_CONGRESS_FEC_CANDIDATE_ID, SMOKE_CONGRESS_PRINCIPAL_FEC_COMMITTEE_ID, SMOKE_CONGRESS_IE_FEC_COMMITTEE_ID, SMOKE_CONGRESS_IE_FEC_COMMITTEE_B_ID, scenarioSlug, zctaInDistrict, zctaOutOfDistrict } = fixture;
  const transactionIdentifiers = [`smoke-${scenarioSlug}-ie-support`, `smoke-${scenarioSlug}-ie-oppose`, `smoke-${scenarioSlug}-receipt-january`, `smoke-${scenarioSlug}-receipt-february`];
  return `DELETE FROM cf.transaction
WHERE id IN (
  ${sqlUuid(SMOKE_CONGRESS_IE_SUPPORT_TRANSACTION_ID, "SMOKE_CONGRESS_IE_SUPPORT_TRANSACTION_ID")},
  ${sqlUuid(SMOKE_CONGRESS_IE_OPPOSE_TRANSACTION_ID, "SMOKE_CONGRESS_IE_OPPOSE_TRANSACTION_ID")},
  ${sqlUuid(SMOKE_CONGRESS_RECEIPT_JANUARY_ID, "SMOKE_CONGRESS_RECEIPT_JANUARY_ID")},
  ${sqlUuid(SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID, "SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID")}
)
OR source_record_id = ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
OR transaction_identifier IN (
  ${transactionIdentifiers.map((value) => sqlLiteral(value)).join(",\n  ")}
);
DELETE FROM cf.committee_summary
WHERE id IN (
  ${sqlUuid(SMOKE_CONGRESS_COMMITTEE_SUMMARY_2022_ID, "SMOKE_CONGRESS_COMMITTEE_SUMMARY_2022_ID")},
  ${sqlUuid(SMOKE_CONGRESS_COMMITTEE_SUMMARY_2024_ID, "SMOKE_CONGRESS_COMMITTEE_SUMMARY_2024_ID")},
  ${sqlUuid(SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID, "SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID")}
)
OR source_record_id = ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")};
DELETE FROM cf.filing
WHERE source_record_id = ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
OR filing_fec_id IN (
  ${sqlLiteral(SMOKE_CONGRESS_FILING_FEC_ID)},
  ${sqlLiteral(SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_FEC_ID)},
  ${sqlLiteral(SMOKE_CONGRESS_RECEIPT_FILING_FEC_ID)}
);
DELETE FROM civic.zcta_district
WHERE zcta5 IN (${sqlLiteral(zctaInDistrict)}, ${sqlLiteral(zctaOutOfDistrict)})
  AND source_url = ${sqlLiteral(`https://example.org/${scenarioSlug}-smoke/zcta-district`)};
DELETE FROM cf.candidate_committee_link
WHERE id = ${sqlUuid(SMOKE_CONGRESS_LINK_ID, "SMOKE_CONGRESS_LINK_ID")}
OR source_record_id = ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")};
DELETE FROM cf.candidate
WHERE source_record_id = ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
OR fec_candidate_id = ${sqlLiteral(SMOKE_CONGRESS_FEC_CANDIDATE_ID)};
DELETE FROM cf.committee
WHERE source_record_id = ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
OR fec_committee_id IN (
  ${sqlLiteral(SMOKE_CONGRESS_PRINCIPAL_FEC_COMMITTEE_ID)},
  ${sqlLiteral(SMOKE_CONGRESS_IE_FEC_COMMITTEE_ID)},
  ${sqlLiteral(SMOKE_CONGRESS_IE_FEC_COMMITTEE_B_ID)}
);`;
}

function buildCongressPersonCoreCleanupDeletes(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_SOURCE_RECORD_ID, SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, SMOKE_CONGRESS_OFFICEHOLDING_ID, SMOKE_CONGRESS_PORTRAIT_ID, SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID, SMOKE_CONGRESS_FEC_DATA_SOURCE_ID, SMOKE_CONGRESS_FEC_CANDIDATE_ID, scenarioSlug } = fixture;
  const sourceRecordKeys = [`smoke-${scenarioSlug}-officeholding`, `smoke-${scenarioSlug}-fec-summary`];
  return `DELETE FROM core.person_portrait
WHERE id = ${sqlUuid(SMOKE_CONGRESS_PORTRAIT_ID, "SMOKE_CONGRESS_PORTRAIT_ID")}
OR source_record_id IN (
  ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")},
  ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
);
DELETE FROM civic.officeholding
WHERE id = ${sqlUuid(SMOKE_CONGRESS_OFFICEHOLDING_ID, "SMOKE_CONGRESS_OFFICEHOLDING_ID")}
OR source_record_id = ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")};
DELETE FROM civic.office AS office
WHERE office.id = ${sqlUuid(SMOKE_OFFICE_ID, "SMOKE_OFFICE_ID")}
  AND office.source_record_id = ${sqlUuid(SMOKE_SHARED_OFFICE_SOURCE_RECORD_ID, "SMOKE_SHARED_OFFICE_SOURCE_RECORD_ID")}
  AND NOT EXISTS (
    SELECT 1
    FROM civic.officeholding AS officeholding
    WHERE officeholding.office_id = office.id
  );
DELETE FROM civic.electoral_division
WHERE source_record_id = ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")};
DELETE FROM core.source_record
WHERE id IN (
  ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")},
  ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
)
OR source_record_key IN (${sourceRecordKeys.map((value) => sqlLiteral(value)).join(", ")});
DELETE FROM core.source_record AS source_record
WHERE source_record.id = ${sqlUuid(SMOKE_SHARED_OFFICE_SOURCE_RECORD_ID, "SMOKE_SHARED_OFFICE_SOURCE_RECORD_ID")}
  AND NOT EXISTS (
    SELECT 1
    FROM civic.office AS office
    WHERE office.source_record_id = source_record.id
  );
DELETE FROM core.data_source
WHERE id IN (
  ${sqlUuid(SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID, "SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID")},
  ${sqlUuid(SMOKE_CONGRESS_FEC_DATA_SOURCE_ID, "SMOKE_CONGRESS_FEC_DATA_SOURCE_ID")}
);
DELETE FROM core.data_source AS data_source
WHERE data_source.id = ${sqlUuid(SMOKE_SHARED_OFFICE_DATA_SOURCE_ID, "SMOKE_SHARED_OFFICE_DATA_SOURCE_ID")}
  AND NOT EXISTS (
    SELECT 1
    FROM core.source_record AS source_record
    WHERE source_record.data_source_id = data_source.id
  );
DELETE FROM core.person
WHERE identifiers ->> 'fec_candidate_id' = ${sqlLiteral(SMOKE_CONGRESS_FEC_CANDIDATE_ID)};`;
}

export function buildCongressPersonSmokeSeedSql(fixture: CongressPersonSmokeFixture): string {
  const cleanupSql = buildCongressPersonSmokeCleanupSql(fixture);
  return `
${cleanupSql}
BEGIN;
${buildSmokeDataSourceInserts(fixture)}
${buildSmokeSourceRecordInserts(fixture)}
${buildSmokeCivicIdentityInserts(fixture)}
${buildSmokeOfficeAndPortraitInserts(fixture)}
${buildSmokeCommitteeInserts(fixture)}
${buildSmokeCandidateAndLinkInserts(fixture)}
${buildSmokeFilingInserts(fixture)}
${buildSmokeCommitteeSummaryInserts(fixture)}
${buildSmokeZctaInserts(fixture)}
${buildSmokeTransactionInserts(fixture)}
COMMIT;
`;
}

function buildSmokeDataSourceInserts(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID, SMOKE_CONGRESS_FEC_DATA_SOURCE_ID, sourceNamePrefix } = fixture;
  const sourceBaseUrl = smokeSourceBaseUrl(fixture);
  return `INSERT INTO core.data_source (id, domain, jurisdiction, name, source_url, source_format, license, update_frequency)
VALUES
  (
    ${sqlUuid(SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID, "SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID")},
    'civics',
    'federal/us',
    ${sqlLiteral(`${sourceNamePrefix} smoke civic source`)},
    ${sqlLiteral(`${sourceBaseUrl}/civics`)},
    'api',
    'public_domain',
    'weekly'
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_FEC_DATA_SOURCE_ID, "SMOKE_CONGRESS_FEC_DATA_SOURCE_ID")},
    'campaign_finance',
    'federal/fec',
    ${sqlLiteral(`${sourceNamePrefix} smoke FEC source`)},
    ${sqlLiteral(`${sourceBaseUrl}/fec`)},
    'csv',
    'public_domain',
    'weekly'
  );
INSERT INTO core.data_source (id, domain, jurisdiction, name, source_url, source_format, license, update_frequency)
VALUES (
  ${sqlUuid(SMOKE_SHARED_OFFICE_DATA_SOURCE_ID, "SMOKE_SHARED_OFFICE_DATA_SOURCE_ID")},
  'civics',
  'federal/us',
  'Shared smoke federal office source',
  'https://example.org/shared-office-smoke',
  'api',
  'public_domain',
  'weekly'
)
ON CONFLICT DO NOTHING;`;
}

function buildSmokeSourceRecordInserts(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_SOURCE_RECORD_ID, SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID, SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, SMOKE_CONGRESS_FEC_DATA_SOURCE_ID, SMOKE_CONGRESS_FEC_CANDIDATE_ID, SMOKE_CONGRESS_PRINCIPAL_FEC_COMMITTEE_ID, scenarioSlug } = fixture;
  const sourceBaseUrl = smokeSourceBaseUrl(fixture);
  return `INSERT INTO core.source_record (id, data_source_id, source_record_key, source_url, raw_fields, pull_date, record_hash)
VALUES (
  ${sqlUuid(SMOKE_SHARED_OFFICE_SOURCE_RECORD_ID, "SMOKE_SHARED_OFFICE_SOURCE_RECORD_ID")},
  ${sqlUuid(SMOKE_SHARED_OFFICE_DATA_SOURCE_ID, "SMOKE_SHARED_OFFICE_DATA_SOURCE_ID")},
  'smoke-shared-federal-office',
  'https://example.org/shared-office-smoke/office',
  ${jsonbLiteral({ office: "us_house" })},
  '2026-06-01T12:00:00Z',
  'smoke-shared-federal-office-hash'
)
ON CONFLICT DO NOTHING;
INSERT INTO core.source_record (id, data_source_id, source_record_key, source_url, raw_fields, pull_date, record_hash)
VALUES
  (
    ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")},
    ${sqlUuid(SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID, "SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID")},
    ${sqlLiteral(`smoke-${scenarioSlug}-officeholding`)},
    ${sqlLiteral(`${sourceBaseUrl}/officeholding`)},
    ${jsonbLiteral({ member_name: SMOKE_PERSON_CANONICAL_NAME, party: "DEM" })},
    '2026-06-01T12:00:00Z',
    ${sqlLiteral(`smoke-${scenarioSlug}-officeholding-hash`)}
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    ${sqlUuid(SMOKE_CONGRESS_FEC_DATA_SOURCE_ID, "SMOKE_CONGRESS_FEC_DATA_SOURCE_ID")},
    ${sqlLiteral(`smoke-${scenarioSlug}-fec-summary`)},
    ${sqlLiteral(`${sourceBaseUrl}/fec-summary`)},
    ${jsonbLiteral({
      fec_candidate_id: SMOKE_CONGRESS_FEC_CANDIDATE_ID,
      fec_committee_id: SMOKE_CONGRESS_PRINCIPAL_FEC_COMMITTEE_ID
    })},
    '2026-06-01T12:00:00Z',
    ${sqlLiteral(`smoke-${scenarioSlug}-fec-summary-hash`)}
  );`;
}

function buildSmokeCivicIdentityInserts(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_PERSON_ID, SMOKE_CONGRESS_FEC_CANDIDATE_ID, SMOKE_CONGRESS_DIVISION_ID, SMOKE_CONGRESS_SOURCE_RECORD_ID, divisionName } = fixture;
  return `INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
VALUES (
  ${sqlUuid(SMOKE_CONGRESS_PERSON_ID, "SMOKE_CONGRESS_PERSON_ID")},
  ${sqlLiteral(SMOKE_PERSON_CANONICAL_NAME)},
  'Jane',
  'Doe',
  ${jsonbLiteral({ fec_candidate_id: SMOKE_CONGRESS_FEC_CANDIDATE_ID })}
);
INSERT INTO civic.electoral_division (
  id, name, division_type, state, district_number, boundary_year, geometry, source_record_id
)
VALUES (
  ${sqlUuid(SMOKE_CONGRESS_DIVISION_ID, "SMOKE_CONGRESS_DIVISION_ID")},
  ${sqlLiteral(divisionName)},
  'congressional_district',
  'NC',
  '01',
  2024,
  ST_GeomFromText('MULTIPOLYGON(((-78.95 35.86,-78.73 35.86,-78.73 36.07,-78.95 36.07,-78.95 35.86)))', 4326),
  ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")}
)
ON CONFLICT DO NOTHING;`;
}

function buildSmokeOfficeAndPortraitInserts(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_OFFICEHOLDING_ID, SMOKE_CONGRESS_PERSON_ID, SMOKE_CONGRESS_SOURCE_RECORD_ID, SMOKE_CONGRESS_PORTRAIT_ID, divisionName, portraitHash, scenarioSlug } = fixture;
  return `INSERT INTO civic.office (
  id, name, office_level, title, jurisdiction_id, state, electoral_division_id, is_elected, number_of_seats, source_record_id
)
VALUES (
  ${sqlUuid(SMOKE_OFFICE_ID, "SMOKE_OFFICE_ID")},
  'us_house',
  'federal',
  'Representative',
  NULL,
  NULL,
  NULL,
  TRUE,
  1,
  ${sqlUuid(SMOKE_SHARED_OFFICE_SOURCE_RECORD_ID, "SMOKE_SHARED_OFFICE_SOURCE_RECORD_ID")}
)
ON CONFLICT DO NOTHING;
INSERT INTO civic.officeholding (
  id, person_id, office_id, electoral_division_id, holder_status, valid_period, date_precision, source_record_id
)
VALUES (
  ${sqlUuid(SMOKE_CONGRESS_OFFICEHOLDING_ID, "SMOKE_CONGRESS_OFFICEHOLDING_ID")},
  ${sqlUuid(SMOKE_CONGRESS_PERSON_ID, "SMOKE_CONGRESS_PERSON_ID")},
  (
    SELECT id FROM civic.office
    WHERE office_level = 'federal'
      AND state IS NULL
      AND name = 'us_house'
      AND electoral_division_id IS NULL
    ORDER BY id ASC
    LIMIT 1
  ),
  (
    SELECT id FROM civic.electoral_division
    WHERE division_type = 'congressional_district'
      AND state = 'NC'
      AND name = ${sqlLiteral(divisionName)}
      AND boundary_year = 2024
    ORDER BY id ASC
    LIMIT 1
  ),
  'elected',
  '[2025-01-03,2100-01-01)'::daterange,
  'day',
  ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")}
);
INSERT INTO core.person_portrait (
  id, person_id, source_record_id, status, rights_status, image_hash, dedup_key, mime_type, width_px, height_px, source_image_url, storage_uri
)
VALUES (
  ${sqlUuid(SMOKE_CONGRESS_PORTRAIT_ID, "SMOKE_CONGRESS_PORTRAIT_ID")},
  ${sqlUuid(SMOKE_CONGRESS_PERSON_ID, "SMOKE_CONGRESS_PERSON_ID")},
  ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")},
  'active',
  'public_domain',
  ${sqlLiteral(portraitHash)},
  ${sqlLiteral(`smoke-${scenarioSlug}-portrait`)},
  'image/gif',
  1,
  1,
  ${sqlLiteral(SMOKE_CONGRESS_PORTRAIT_URL)},
  ${sqlLiteral(`s3://civibus/smoke/${scenarioSlug}-portrait.gif`)}
);`;
}

function buildSmokeCommitteeInserts(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, SMOKE_CONGRESS_PRINCIPAL_FEC_COMMITTEE_ID, SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, SMOKE_CONGRESS_IE_COMMITTEE_ID, SMOKE_CONGRESS_IE_FEC_COMMITTEE_ID, SMOKE_CONGRESS_IE_COMMITTEE_B_ID, SMOKE_CONGRESS_IE_FEC_COMMITTEE_B_ID, zctaOutOfDistrict } = fixture;
  return `INSERT INTO cf.committee (
  id, fec_committee_id, name, source_record_id, committee_type, committee_designation, party, state, city, zip_code, treasurer_name
)
VALUES
  (
    ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
    ${sqlLiteral(SMOKE_CONGRESS_PRINCIPAL_FEC_COMMITTEE_ID)},
    ${sqlLiteral(SMOKE_COMMITTEE_NAME)},
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    'H',
    'P',
    'DEM',
    'NC',
    'Raleigh',
    ${sqlLiteral(zctaOutOfDistrict)},
    'Smoke Treasurer'
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_IE_COMMITTEE_ID, "SMOKE_CONGRESS_IE_COMMITTEE_ID")},
    ${sqlLiteral(SMOKE_CONGRESS_IE_FEC_COMMITTEE_ID)},
    ${sqlLiteral(SMOKE_IE_COMMITTEE_A_NAME)},
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    'O',
    'U',
    NULL,
    'NC',
    'Raleigh',
    ${sqlLiteral(zctaOutOfDistrict)},
    'IE Treasurer'
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_IE_COMMITTEE_B_ID, "SMOKE_CONGRESS_IE_COMMITTEE_B_ID")},
    ${sqlLiteral(SMOKE_CONGRESS_IE_FEC_COMMITTEE_B_ID)},
    ${sqlLiteral(SMOKE_FINANCE_LIVE_IE_COMMITTEE_B_NAME)},
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    'O',
    'U',
    NULL,
    'NC',
    'Raleigh',
    ${sqlLiteral(zctaOutOfDistrict)},
    'IE Treasurer'
  );`;
}

function buildSmokeCandidateAndLinkInserts(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_CANDIDATE_ID, SMOKE_CONGRESS_FEC_CANDIDATE_ID, SMOKE_CONGRESS_PERSON_ID, SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, SMOKE_CONGRESS_LINK_ID } = fixture;
  return `INSERT INTO cf.candidate (
  id, fec_candidate_id, name, office, person_id, principal_committee_id, source_record_id, party, state, district,
  incumbent_challenge, total_receipts, total_disbursements, cash_on_hand, summary_coverage_end_date
)
VALUES (
  ${sqlUuid(SMOKE_CONGRESS_CANDIDATE_ID, "SMOKE_CONGRESS_CANDIDATE_ID")},
  ${sqlLiteral(SMOKE_CONGRESS_FEC_CANDIDATE_ID)},
  ${sqlLiteral(SMOKE_CANDIDATE_NAME)},
  'H',
  ${sqlUuid(SMOKE_CONGRESS_PERSON_ID, "SMOKE_CONGRESS_PERSON_ID")},
  ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
  ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
  'DEM',
  'NC',
  '01',
  'I',
  ${moneyLiteral(SMOKE_CANDIDATE_TOTAL_RAISED)},
  ${moneyLiteral(SMOKE_CANDIDATE_TOTAL_SPENT)},
  ${moneyLiteral(SMOKE_PERSON_CASH_ON_HAND_DOLLARS)},
  '2026-03-19'
);
INSERT INTO cf.candidate_committee_link (
  id, candidate_id, committee_id, designation, candidate_election_year, fec_election_year, valid_period, source_record_id
)
VALUES (
  ${sqlUuid(SMOKE_CONGRESS_LINK_ID, "SMOKE_CONGRESS_LINK_ID")},
  ${sqlUuid(SMOKE_CONGRESS_CANDIDATE_ID, "SMOKE_CONGRESS_CANDIDATE_ID")},
  ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
  'P',
  2026,
  2026,
  '[2025-01-01,2100-01-01)'::daterange,
  ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
);`;
}

function buildSmokeFilingInserts(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_FILING_ID, SMOKE_CONGRESS_FILING_FEC_ID, SMOKE_CONGRESS_IE_COMMITTEE_ID, SMOKE_CONGRESS_CANDIDATE_ID, SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, SMOKE_CONGRESS_RECEIPT_FILING_ID, SMOKE_CONGRESS_RECEIPT_FILING_FEC_ID, SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_ID, SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_FEC_ID, SMOKE_CONGRESS_IE_COMMITTEE_B_ID } = fixture;
  return `INSERT INTO cf.filing (
  id, filing_fec_id, committee_id, candidate_id, report_type, amendment_indicator, filing_name,
  coverage_start_date, coverage_end_date, receipt_date, accepted_date, source_record_id
)
VALUES
  (
    ${sqlUuid(SMOKE_CONGRESS_FILING_ID, "SMOKE_CONGRESS_FILING_ID")},
    ${sqlLiteral(SMOKE_CONGRESS_FILING_FEC_ID)},
    ${sqlUuid(SMOKE_CONGRESS_IE_COMMITTEE_ID, "SMOKE_CONGRESS_IE_COMMITTEE_ID")},
    ${sqlUuid(SMOKE_CONGRESS_CANDIDATE_ID, "SMOKE_CONGRESS_CANDIDATE_ID")},
    'SE',
    'N',
    'Schedule E smoke filing',
    '2026-01-01',
    '2026-03-31',
    '2026-04-15',
    '2026-04-15',
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_RECEIPT_FILING_ID, "SMOKE_CONGRESS_RECEIPT_FILING_ID")},
    ${sqlLiteral(SMOKE_CONGRESS_RECEIPT_FILING_FEC_ID)},
    ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
    ${sqlUuid(SMOKE_CONGRESS_CANDIDATE_ID, "SMOKE_CONGRESS_CANDIDATE_ID")},
    'F3',
    'N',
    'Receipt smoke filing',
    '2026-01-01',
    '2026-03-31',
    '2026-04-15',
    '2026-04-15',
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_ID, "SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_ID")},
    ${sqlLiteral(SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_FEC_ID)},
    ${sqlUuid(SMOKE_CONGRESS_IE_COMMITTEE_B_ID, "SMOKE_CONGRESS_IE_COMMITTEE_B_ID")},
    ${sqlUuid(SMOKE_CONGRESS_CANDIDATE_ID, "SMOKE_CONGRESS_CANDIDATE_ID")},
    'SE',
    'N',
    'Schedule E smoke filing',
    '2026-01-01',
    '2026-03-31',
    '2026-04-15',
    '2026-04-15',
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
  );`;
}

function buildSmokeCommitteeSummaryInserts(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_COMMITTEE_SUMMARY_2022_ID, SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, SMOKE_CONGRESS_COMMITTEE_SUMMARY_2024_ID, SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID, scenarioSlug } = fixture;
  // The charts scenario needs a renderable receipt-source composition: the 2026
  // committee summary must cover the whole selected cycle and carry an itemized
  // individual/PAC breakdown that reconciles to total_receipts (equal to the
  // candidate's official total_raised, which is the composition share denominator).
  // The directory scenario keeps its minimal half-cycle summary — no live test
  // asserts its receipt composition.
  const isChartsScenario = scenarioSlug === "person-charts";
  const currentSummaryCoverageEnd = isChartsScenario ? SMOKE_CHART_LIVE_SUMMARY_COVERAGE_END : "2026-06-30";
  const currentSummaryTotalReceipts = isChartsScenario
    ? SMOKE_CHART_LIVE_RECEIPT_TOTAL_DOLLARS
    : SMOKE_PERSON_TOTAL_CONTRIBUTION_DOLLARS;
  const currentSummaryIndividual = isChartsScenario ? moneyLiteral(SMOKE_CHART_LIVE_RECEIPT_INDIVIDUAL_DOLLARS) : "NULL";
  const currentSummaryPac = isChartsScenario ? moneyLiteral(SMOKE_CHART_LIVE_RECEIPT_PAC_DOLLARS) : "NULL";
  return `INSERT INTO cf.committee_summary (
  id, committee_id, source_record_id, cycle, committee_name, coverage_start_date, coverage_end_date,
  total_receipts, total_disbursements, cash_on_hand, individual_unitemized_contributions,
  individual_contributions, other_committee_contributions
)
VALUES
  (
    ${sqlUuid(SMOKE_CONGRESS_COMMITTEE_SUMMARY_2022_ID, "SMOKE_CONGRESS_COMMITTEE_SUMMARY_2022_ID")},
    ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    2022,
    ${sqlLiteral(SMOKE_COMMITTEE_NAME)},
    '2021-01-01',
    '2022-12-31',
    0.00,
    0.00,
    0.00,
    0.00,
    NULL,
    NULL
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_COMMITTEE_SUMMARY_2024_ID, "SMOKE_CONGRESS_COMMITTEE_SUMMARY_2024_ID")},
    ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    2024,
    ${sqlLiteral(SMOKE_COMMITTEE_NAME)},
    '2023-01-01',
    '2024-12-31',
    ${moneyLiteral(SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS)},
    0.00,
    0.00,
    ${moneyLiteral(SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS)},
    NULL,
    NULL
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID, "SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID")},
    ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    2026,
    ${sqlLiteral(SMOKE_COMMITTEE_NAME)},
    '2025-01-01',
    '${currentSummaryCoverageEnd}',
    ${moneyLiteral(currentSummaryTotalReceipts)},
    ${moneyLiteral(SMOKE_CANDIDATE_TOTAL_SPENT)},
    ${moneyLiteral(SMOKE_PERSON_CASH_ON_HAND_DOLLARS)},
    ${moneyLiteral(SMOKE_PERSON_UNITEMIZED_DOLLARS)},
    ${currentSummaryIndividual},
    ${currentSummaryPac}
  );`;
}

function buildSmokeZctaInserts(fixture: CongressPersonSmokeFixture): string {
  const { zctaInDistrict, zctaOutOfDistrict } = fixture;
  const sourceBaseUrl = smokeSourceBaseUrl(fixture);
  return `INSERT INTO civic.zcta_district (zcta5, boundary_year, state_fips, cd_geoid, district_number, land_share, source_url)
VALUES
  (${sqlLiteral(zctaInDistrict)}, 2024, '37', '3701', '01', 1.00000, ${sqlLiteral(`${sourceBaseUrl}/zcta-district`)}),
  (${sqlLiteral(zctaOutOfDistrict)}, 2024, '37', '3702', '02', 1.00000, ${sqlLiteral(`${sourceBaseUrl}/zcta-district`)})
ON CONFLICT (zcta5, boundary_year) DO UPDATE
SET state_fips = EXCLUDED.state_fips,
    cd_geoid = EXCLUDED.cd_geoid,
    district_number = EXCLUDED.district_number,
    land_share = EXCLUDED.land_share,
    source_url = EXCLUDED.source_url;`;
}

function buildSmokeTransactionInserts(fixture: CongressPersonSmokeFixture): string {
  const transactionIdentifier = (suffix: string) => `smoke-${fixture.scenarioSlug}-${suffix}`;
  const ieTransactionRows = buildCongressPersonIeTransactionRows(fixture, transactionIdentifier);
  const receiptTransactionRows = buildCongressPersonReceiptTransactionRows(fixture, transactionIdentifier);
  return `INSERT INTO cf.transaction (
  id, filing_id, committee_id, transaction_type, source_record_id, transaction_identifier, transaction_date,
  amount, recipient_candidate_id, memo_text, is_memo, amendment_indicator, date_is_reliable,
  support_oppose, dissemination_date, aggregate_amount
)
VALUES
  ${ieTransactionRows};
INSERT INTO cf.transaction (
  id, filing_id, committee_id, transaction_type, source_record_id, transaction_identifier, transaction_date,
  amount, contributor_name_raw, contributor_employer, contributor_state, contributor_zip, contributor_entity_type,
  memo_text, is_memo, amendment_indicator, date_is_reliable
)
VALUES
  ${receiptTransactionRows};`;
}

export function buildCongressPersonGraphMergeSql(fixture: CongressPersonSmokeFixture): string {
  const { SMOKE_CONGRESS_PERSON_ID } = fixture;
  return `LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT ag_catalog.create_graph('civibus')
WHERE NOT EXISTS (
  SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'civibus'
);
SELECT *
FROM ag_catalog.cypher('civibus', $$
  MERGE (n:Person {id: "${cypherString(SMOKE_CONGRESS_PERSON_ID)}"})
  SET n.canonical_name = "${cypherString(SMOKE_PERSON_CANONICAL_NAME)}"
$$) AS (v agtype);`;
}
