// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { SMOKE_CANDIDATE_NAME, SMOKE_CANDIDATE_OPPOSE_TOTAL, SMOKE_CANDIDATE_SUPPORT_TOTAL, SMOKE_CANDIDATE_TOTAL_RAISED, SMOKE_CANDIDATE_TOTAL_SPENT, SMOKE_COMMITTEE_NAME, SMOKE_CONGRESS_CANDIDATE_ID, SMOKE_CONGRESS_FILING_ID, SMOKE_CONGRESS_IE_COMMITTEE_ID, SMOKE_CONGRESS_PERSON_ID, SMOKE_CONGRESS_PORTRAIT_URL, SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, SMOKE_IE_COMMITTEE_A_NAME, SMOKE_OFFICE_ID, SMOKE_PERSON_CASH_ON_HAND_DOLLARS, SMOKE_PERSON_CANONICAL_NAME, SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS, SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS, SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS, SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME, SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME, SMOKE_PERSON_TOTAL_CONTRIBUTION_DOLLARS, SMOKE_PERSON_UNITEMIZED_DOLLARS, SMOKE_SEARCH_LIVE_PERSON_NAME } from "./fixtures.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { cypherString, jsonbLiteral, moneyLiteral, runSmokeSeedSql, sqlLiteral, sqlUuid, type SmokeSeedCleanupCallback } from "./smoke_seed_helpers.ts";

const SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID = "90000000-0000-4000-8000-000000000401";
const SMOKE_CONGRESS_FEC_DATA_SOURCE_ID = "90000000-0000-4000-8000-000000000402";
const SMOKE_CONGRESS_SOURCE_RECORD_ID = "90000000-0000-4000-8000-000000000403";
const SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID = "90000000-0000-4000-8000-000000000404";
const SMOKE_CONGRESS_DIVISION_ID = "90000000-0000-4000-8000-000000000405";
const SMOKE_CONGRESS_OFFICEHOLDING_ID = "90000000-0000-4000-8000-000000000406";
const SMOKE_CONGRESS_PORTRAIT_ID = "90000000-0000-4000-8000-000000000407";
const SMOKE_CONGRESS_LINK_ID = "90000000-0000-4000-8000-000000000408";
const SMOKE_CONGRESS_IE_SUPPORT_TRANSACTION_ID = "90000000-0000-4000-8000-000000000409";
const SMOKE_CONGRESS_IE_OPPOSE_TRANSACTION_ID = "90000000-0000-4000-8000-000000000410";
const SMOKE_CONGRESS_RECEIPT_FILING_ID = "90000000-0000-4000-8000-000000000411";
const SMOKE_CONGRESS_RECEIPT_JANUARY_ID = "90000000-0000-4000-8000-000000000412";
const SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID = "90000000-0000-4000-8000-000000000413";
const SMOKE_CONGRESS_COMMITTEE_SUMMARY_2022_ID = "90000000-0000-4000-8000-000000000414";
const SMOKE_CONGRESS_COMMITTEE_SUMMARY_2024_ID = "90000000-0000-4000-8000-000000000415";
const SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID = "90000000-0000-4000-8000-000000000416";
const SMOKE_CONGRESS_FEC_CANDIDATE_ID = "H0NC01999";
const SMOKE_CONGRESS_PRINCIPAL_FEC_COMMITTEE_ID = "C90000001";
const SMOKE_CONGRESS_IE_FEC_COMMITTEE_ID = "C90000002";
const SMOKE_CONGRESS_FILING_FEC_ID = "smoke-congress-filing-2026-q1";
const SMOKE_CONGRESS_RECEIPT_FILING_FEC_ID = "smoke-congress-receipts-2026-q1";

const SMOKE_SEARCH_LIVE_DATA_SOURCE_ID = "90000000-0000-4000-8000-000000000501";
const SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID = "90000000-0000-4000-8000-000000000502";
const SMOKE_SEARCH_LIVE_PERSON_ID = "90000000-0000-4000-8000-000000000503";
const SMOKE_SEARCH_LIVE_DIVISION_ID = "90000000-0000-4000-8000-000000000504";
const SMOKE_SEARCH_LIVE_OFFICE_ID = "90000000-0000-4000-8000-000000000505";
const SMOKE_SEARCH_LIVE_OFFICEHOLDING_ID = "90000000-0000-4000-8000-000000000506";
const SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_ID = "90000000-0000-4000-8000-000000000507";
const SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_FEC_ID = "C90005001";
const SMOKE_SEARCH_LIVE_DIVISION_NAME = "nc_cd_02_smoke";

/**
 */
export function buildCongressSmokeCleanupSql(): string {
  return `
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT ag_catalog.create_graph('civibus')
WHERE NOT EXISTS (
  SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'civibus'
);
SELECT *
FROM ag_catalog.cypher('civibus', $$
  MATCH (n:Person {id: "${cypherString(SMOKE_CONGRESS_PERSON_ID)}"})
  DETACH DELETE n
$$) AS (v agtype);
BEGIN;
DELETE FROM cf.transaction
WHERE id IN (
  ${sqlUuid(SMOKE_CONGRESS_IE_SUPPORT_TRANSACTION_ID, "SMOKE_CONGRESS_IE_SUPPORT_TRANSACTION_ID")},
  ${sqlUuid(SMOKE_CONGRESS_IE_OPPOSE_TRANSACTION_ID, "SMOKE_CONGRESS_IE_OPPOSE_TRANSACTION_ID")},
  ${sqlUuid(SMOKE_CONGRESS_RECEIPT_JANUARY_ID, "SMOKE_CONGRESS_RECEIPT_JANUARY_ID")},
  ${sqlUuid(SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID, "SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID")}
)
OR source_record_id = ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
OR transaction_identifier IN (
  'smoke-congress-ie-support',
  'smoke-congress-ie-oppose',
  'smoke-congress-receipt-january',
  'smoke-congress-receipt-february'
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
  ${sqlLiteral(SMOKE_CONGRESS_RECEIPT_FILING_FEC_ID)}
);
DELETE FROM civic.zcta_district
WHERE zcta5 IN ('27513', '27601')
  AND source_url = 'https://example.org/congress-smoke/zcta-district';
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
  ${sqlLiteral(SMOKE_CONGRESS_IE_FEC_COMMITTEE_ID)}
);
DELETE FROM core.person_portrait
WHERE id = ${sqlUuid(SMOKE_CONGRESS_PORTRAIT_ID, "SMOKE_CONGRESS_PORTRAIT_ID")}
OR source_record_id IN (
  ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")},
  ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
);
DELETE FROM civic.officeholding
WHERE id = ${sqlUuid(SMOKE_CONGRESS_OFFICEHOLDING_ID, "SMOKE_CONGRESS_OFFICEHOLDING_ID")}
OR source_record_id = ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")};
DELETE FROM civic.office
WHERE source_record_id = ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")};
DELETE FROM civic.electoral_division
WHERE source_record_id = ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")};
DELETE FROM core.source_record
WHERE id IN (
  ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")},
  ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}
)
OR source_record_key IN ('smoke-congress-officeholding', 'smoke-congress-fec-summary');
DELETE FROM core.data_source
WHERE id IN (
  ${sqlUuid(SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID, "SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID")},
  ${sqlUuid(SMOKE_CONGRESS_FEC_DATA_SOURCE_ID, "SMOKE_CONGRESS_FEC_DATA_SOURCE_ID")}
);
DELETE FROM core.person
WHERE identifiers ->> 'fec_candidate_id' = ${sqlLiteral(SMOKE_CONGRESS_FEC_CANDIDATE_ID)};
COMMIT;
`;
}

/**
 */
export function buildCongressSmokeSeedSql(): string {
  const cleanupSql = buildCongressSmokeCleanupSql();
  return `
${cleanupSql}
BEGIN;
INSERT INTO core.data_source (id, domain, jurisdiction, name, source_url, source_format, license, update_frequency)
VALUES
  (
    ${sqlUuid(SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID, "SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID")},
    'civics',
    'federal/us',
    'Congress smoke civic source',
    'https://example.org/congress-smoke/civics',
    'api',
    'public_domain',
    'weekly'
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_FEC_DATA_SOURCE_ID, "SMOKE_CONGRESS_FEC_DATA_SOURCE_ID")},
    'campaign_finance',
    'federal/fec',
    'Congress smoke FEC source',
    'https://example.org/congress-smoke/fec',
    'csv',
    'public_domain',
    'weekly'
  );
INSERT INTO core.source_record (id, data_source_id, source_record_key, source_url, raw_fields, pull_date, record_hash)
VALUES
  (
    ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")},
    ${sqlUuid(SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID, "SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID")},
    'smoke-congress-officeholding',
    'https://example.org/congress-smoke/officeholding',
    ${jsonbLiteral({ member_name: SMOKE_PERSON_CANONICAL_NAME, party: "DEM" })},
    '2026-06-01T12:00:00Z',
    'smoke-congress-officeholding-hash'
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    ${sqlUuid(SMOKE_CONGRESS_FEC_DATA_SOURCE_ID, "SMOKE_CONGRESS_FEC_DATA_SOURCE_ID")},
    'smoke-congress-fec-summary',
    'https://example.org/congress-smoke/fec-summary',
    ${jsonbLiteral({
      fec_candidate_id: SMOKE_CONGRESS_FEC_CANDIDATE_ID,
      fec_committee_id: SMOKE_CONGRESS_PRINCIPAL_FEC_COMMITTEE_ID
    })},
    '2026-06-01T12:00:00Z',
    'smoke-congress-fec-summary-hash'
  );
INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
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
  'nc_cd_01',
  'congressional_district',
  'NC',
  '01',
  2024,
  ST_GeomFromText('MULTIPOLYGON(((-78.95 35.86,-78.73 35.86,-78.73 36.07,-78.95 36.07,-78.95 35.86)))', 4326),
  ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")}
)
ON CONFLICT DO NOTHING;
INSERT INTO civic.office (
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
  ${sqlUuid(SMOKE_CONGRESS_SOURCE_RECORD_ID, "SMOKE_CONGRESS_SOURCE_RECORD_ID")}
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
      AND name = 'nc_cd_01'
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
  'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
  'smoke-congress-portrait',
  'image/gif',
  1,
  1,
  ${sqlLiteral(SMOKE_CONGRESS_PORTRAIT_URL)},
  's3://civibus/smoke/congress-portrait.gif'
);
INSERT INTO cf.committee (
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
    '27601',
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
    '27601',
    'IE Treasurer'
  );
INSERT INTO cf.candidate (
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
  170.00,
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
);
INSERT INTO cf.filing (
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
  );
INSERT INTO cf.committee_summary (
  id, committee_id, source_record_id, cycle, committee_name, coverage_start_date, coverage_end_date,
  total_receipts, total_disbursements, cash_on_hand, individual_unitemized_contributions
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
    0.00
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
    ${moneyLiteral(SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS)}
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID, "SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID")},
    ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    2026,
    ${sqlLiteral(SMOKE_COMMITTEE_NAME)},
    '2025-01-01',
    '2026-06-30',
    ${moneyLiteral(SMOKE_PERSON_TOTAL_CONTRIBUTION_DOLLARS)},
    80.00,
    ${moneyLiteral(SMOKE_PERSON_CASH_ON_HAND_DOLLARS)},
    ${moneyLiteral(SMOKE_PERSON_UNITEMIZED_DOLLARS)}
  );
INSERT INTO civic.zcta_district (zcta5, state_fips, cd_geoid, district_number, land_share, source_url)
VALUES
  ('27513', '37', '3701', '01', 1.00000, 'https://example.org/congress-smoke/zcta-district'),
  ('27601', '37', '3702', '02', 1.00000, 'https://example.org/congress-smoke/zcta-district')
ON CONFLICT (zcta5) DO UPDATE
SET state_fips = EXCLUDED.state_fips,
    cd_geoid = EXCLUDED.cd_geoid,
    district_number = EXCLUDED.district_number,
    land_share = EXCLUDED.land_share,
    source_url = EXCLUDED.source_url;
INSERT INTO cf.transaction (
  id, filing_id, committee_id, transaction_type, source_record_id, transaction_identifier, transaction_date,
  amount, recipient_candidate_id, memo_text, is_memo, amendment_indicator, date_is_reliable,
  support_oppose, dissemination_date, aggregate_amount
)
VALUES
  (
    ${sqlUuid(SMOKE_CONGRESS_IE_SUPPORT_TRANSACTION_ID, "SMOKE_CONGRESS_IE_SUPPORT_TRANSACTION_ID")},
    ${sqlUuid(SMOKE_CONGRESS_FILING_ID, "SMOKE_CONGRESS_FILING_ID")},
    ${sqlUuid(SMOKE_CONGRESS_IE_COMMITTEE_ID, "SMOKE_CONGRESS_IE_COMMITTEE_ID")},
    '24E',
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    'smoke-congress-ie-support',
    '2026-03-20',
    ${moneyLiteral(SMOKE_CANDIDATE_SUPPORT_TOTAL)},
    ${sqlUuid(SMOKE_CONGRESS_CANDIDATE_ID, "SMOKE_CONGRESS_CANDIDATE_ID")},
    'Digital ads',
    FALSE,
    'N',
    TRUE,
    'S',
    '2026-03-20',
    ${moneyLiteral(SMOKE_CANDIDATE_SUPPORT_TOTAL)}
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_IE_OPPOSE_TRANSACTION_ID, "SMOKE_CONGRESS_IE_OPPOSE_TRANSACTION_ID")},
    ${sqlUuid(SMOKE_CONGRESS_FILING_ID, "SMOKE_CONGRESS_FILING_ID")},
    ${sqlUuid(SMOKE_CONGRESS_IE_COMMITTEE_ID, "SMOKE_CONGRESS_IE_COMMITTEE_ID")},
    '24E',
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    'smoke-congress-ie-oppose',
    '2026-03-21',
    ${moneyLiteral(SMOKE_CANDIDATE_OPPOSE_TOTAL)},
    ${sqlUuid(SMOKE_CONGRESS_CANDIDATE_ID, "SMOKE_CONGRESS_CANDIDATE_ID")},
    'Mailers',
    FALSE,
    'N',
    TRUE,
    'O',
    '2026-03-21',
    ${moneyLiteral(SMOKE_CANDIDATE_OPPOSE_TOTAL)}
  );
INSERT INTO cf.transaction (
  id, filing_id, committee_id, transaction_type, source_record_id, transaction_identifier, transaction_date,
  amount, contributor_name_raw, contributor_employer, contributor_state, contributor_zip, contributor_entity_type,
  memo_text, is_memo, amendment_indicator, date_is_reliable
)
VALUES
  (
    ${sqlUuid(SMOKE_CONGRESS_RECEIPT_JANUARY_ID, "SMOKE_CONGRESS_RECEIPT_JANUARY_ID")},
    ${sqlUuid(SMOKE_CONGRESS_RECEIPT_FILING_ID, "SMOKE_CONGRESS_RECEIPT_FILING_ID")},
    ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
    '15',
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    'smoke-congress-receipt-january',
    '2026-01-15',
    ${moneyLiteral(SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS)},
    'Smoke Donor One',
    ${sqlLiteral(SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME)},
    'NC',
    '27513',
    'IND',
    NULL,
    FALSE,
    'N',
    TRUE
  ),
  (
    ${sqlUuid(SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID, "SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID")},
    ${sqlUuid(SMOKE_CONGRESS_RECEIPT_FILING_ID, "SMOKE_CONGRESS_RECEIPT_FILING_ID")},
    ${sqlUuid(SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")},
    '15',
    ${sqlUuid(SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")},
    'smoke-congress-receipt-february',
    '2026-02-15',
    ${moneyLiteral(SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS)},
    'Smoke Donor Two',
    ${sqlLiteral(SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME)},
    'NC',
    '27601',
    'IND',
    NULL,
    FALSE,
    'N',
    TRUE
  );
COMMIT;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT ag_catalog.create_graph('civibus')
WHERE NOT EXISTS (
  SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'civibus'
);
SELECT *
FROM ag_catalog.cypher('civibus', $$
  MERGE (n:Person {id: "${cypherString(SMOKE_CONGRESS_PERSON_ID)}"})
  SET n.canonical_name = "${cypherString(SMOKE_PERSON_CANONICAL_NAME)}"
$$) AS (v agtype);
`;
}

export async function seedLiveCongressDirectorySmoke(): Promise<SmokeSeedCleanupCallback> {
  await runSmokeSeedSql(buildCongressSmokeSeedSql());
  return async () => {
    await runSmokeSeedSql(buildCongressSmokeCleanupSql());
  };
}

/**
 */
function buildSearchOfficeholderSmokeCleanupSql(): string {
  return `
BEGIN;
DELETE FROM cf.committee
WHERE id = ${sqlUuid(SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_ID, "SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_ID")}
   OR fec_committee_id = ${sqlLiteral(SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_FEC_ID)};
DELETE FROM civic.officeholding
WHERE id = ${sqlUuid(SMOKE_SEARCH_LIVE_OFFICEHOLDING_ID, "SMOKE_SEARCH_LIVE_OFFICEHOLDING_ID")}
   OR source_record_id = ${sqlUuid(SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID, "SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID")};
DELETE FROM civic.office
WHERE id = ${sqlUuid(SMOKE_SEARCH_LIVE_OFFICE_ID, "SMOKE_SEARCH_LIVE_OFFICE_ID")}
   OR source_record_id = ${sqlUuid(SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID, "SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID")};
DELETE FROM civic.electoral_division
WHERE id = ${sqlUuid(SMOKE_SEARCH_LIVE_DIVISION_ID, "SMOKE_SEARCH_LIVE_DIVISION_ID")}
   OR source_record_id = ${sqlUuid(SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID, "SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID")};
DELETE FROM core.person
WHERE id = ${sqlUuid(SMOKE_SEARCH_LIVE_PERSON_ID, "SMOKE_SEARCH_LIVE_PERSON_ID")};
DELETE FROM core.source_record
WHERE id = ${sqlUuid(SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID, "SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID")};
DELETE FROM core.data_source
WHERE id = ${sqlUuid(SMOKE_SEARCH_LIVE_DATA_SOURCE_ID, "SMOKE_SEARCH_LIVE_DATA_SOURCE_ID")};
COMMIT;
`;
}

/**
 */
function buildSearchOfficeholderSmokeSeedSql(): string {
  return `
${buildSearchOfficeholderSmokeCleanupSql()}
BEGIN;
INSERT INTO core.data_source (id, domain, jurisdiction, name, source_url, source_format, license, update_frequency)
VALUES (
  ${sqlUuid(SMOKE_SEARCH_LIVE_DATA_SOURCE_ID, "SMOKE_SEARCH_LIVE_DATA_SOURCE_ID")},
  'civics',
  'federal/us',
  'Search officeholder smoke source',
  'https://example.org/search-smoke/civics',
  'api',
  'public_domain',
  'weekly'
);
INSERT INTO core.source_record (id, data_source_id, source_record_key, source_url, raw_fields, pull_date, record_hash)
VALUES (
  ${sqlUuid(SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID, "SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID")},
  ${sqlUuid(SMOKE_SEARCH_LIVE_DATA_SOURCE_ID, "SMOKE_SEARCH_LIVE_DATA_SOURCE_ID")},
  'smoke-search-officeholder',
  'https://example.org/search-smoke/officeholder',
  ${jsonbLiteral({ member_name: SMOKE_SEARCH_LIVE_PERSON_NAME, party: "DEM" })},
  '2026-06-01T12:00:00Z',
  'smoke-search-officeholder-hash'
);
INSERT INTO core.person (id, canonical_name, first_name, last_name)
VALUES (
  ${sqlUuid(SMOKE_SEARCH_LIVE_PERSON_ID, "SMOKE_SEARCH_LIVE_PERSON_ID")},
  ${sqlLiteral(SMOKE_SEARCH_LIVE_PERSON_NAME)},
  'Zorktown',
  'Testperson'
);
INSERT INTO civic.electoral_division (
  id, name, division_type, state, district_number, boundary_year, geometry, source_record_id
)
VALUES (
  ${sqlUuid(SMOKE_SEARCH_LIVE_DIVISION_ID, "SMOKE_SEARCH_LIVE_DIVISION_ID")},
  ${sqlLiteral(SMOKE_SEARCH_LIVE_DIVISION_NAME)},
  'congressional_district',
  'NC',
  '02',
  2024,
  ST_GeomFromText('MULTIPOLYGON(((-79.10 35.50,-78.90 35.50,-78.90 35.70,-79.10 35.70,-79.10 35.50)))', 4326),
  ${sqlUuid(SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID, "SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID")}
);
INSERT INTO civic.office (
  id, name, office_level, title, jurisdiction_id, state, electoral_division_id, is_elected, number_of_seats, source_record_id
)
VALUES (
  ${sqlUuid(SMOKE_SEARCH_LIVE_OFFICE_ID, "SMOKE_SEARCH_LIVE_OFFICE_ID")},
  'us_house',
  'federal',
  'Representative',
  NULL,
  NULL,
  ${sqlUuid(SMOKE_SEARCH_LIVE_DIVISION_ID, "SMOKE_SEARCH_LIVE_DIVISION_ID")},
  TRUE,
  1,
  ${sqlUuid(SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID, "SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID")}
);
INSERT INTO civic.officeholding (
  id, person_id, office_id, electoral_division_id, holder_status, valid_period, date_precision, source_record_id
)
VALUES (
  ${sqlUuid(SMOKE_SEARCH_LIVE_OFFICEHOLDING_ID, "SMOKE_SEARCH_LIVE_OFFICEHOLDING_ID")},
  ${sqlUuid(SMOKE_SEARCH_LIVE_PERSON_ID, "SMOKE_SEARCH_LIVE_PERSON_ID")},
  ${sqlUuid(SMOKE_SEARCH_LIVE_OFFICE_ID, "SMOKE_SEARCH_LIVE_OFFICE_ID")},
  ${sqlUuid(SMOKE_SEARCH_LIVE_DIVISION_ID, "SMOKE_SEARCH_LIVE_DIVISION_ID")},
  'elected',
  '[2025-01-03,2100-01-01)'::daterange,
  'day',
  ${sqlUuid(SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID, "SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID")}
);
INSERT INTO cf.committee (
  id, fec_committee_id, name, source_record_id, committee_type, committee_designation, party, state, city, zip_code, treasurer_name
)
VALUES (
  ${sqlUuid(SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_ID, "SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_ID")},
  ${sqlLiteral(SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_FEC_ID)},
  ${sqlLiteral(SMOKE_SEARCH_LIVE_PERSON_NAME)},
  ${sqlUuid(SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID, "SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID")},
  'N',
  'U',
  NULL,
  NULL,
  NULL,
  NULL,
  'Smoke Same-Name Treasurer'
);
COMMIT;
`;
}

export async function seedLiveSearchOfficeholderSmoke(): Promise<SmokeSeedCleanupCallback> {
  await runSmokeSeedSql(buildSearchOfficeholderSmokeSeedSql());
  return async () => {
    await runSmokeSeedSql(buildSearchOfficeholderSmokeCleanupSql());
  };
}
