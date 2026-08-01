/**
 * Search officeholder smoke seed/cleanup owner.
 *
 * Seeds a distinctly-named officeholder plus a same-name committee so the live search
 * proof can assert person-vs-committee disambiguation. Public entry point is
 * `seedLiveSearchOfficeholderSmoke`, re-exported through ./smoke-seed-sql.ts.
 */
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { SMOKE_SEARCH_LIVE_PERSON_NAME } from "./fixtures.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { jsonbLiteral, runSmokeSeedSql, sqlLiteral, sqlUuid, type SmokeSeedCleanupCallback } from "./smoke_seed_helpers.ts";

const SMOKE_SEARCH_LIVE_DATA_SOURCE_ID = "90000000-0000-4000-8000-000000000501";
const SMOKE_SEARCH_LIVE_SOURCE_RECORD_ID = "90000000-0000-4000-8000-000000000502";
const SMOKE_SEARCH_LIVE_PERSON_ID = "90000000-0000-4000-8000-000000000503";
const SMOKE_SEARCH_LIVE_DIVISION_ID = "90000000-0000-4000-8000-000000000504";
const SMOKE_SEARCH_LIVE_OFFICE_ID = "90000000-0000-4000-8000-000000000505";
const SMOKE_SEARCH_LIVE_OFFICEHOLDING_ID = "90000000-0000-4000-8000-000000000506";
const SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_ID = "90000000-0000-4000-8000-000000000507";
const SMOKE_SEARCH_LIVE_SAME_NAME_COMMITTEE_FEC_ID = "C90005001";
const SMOKE_SEARCH_LIVE_DIVISION_NAME = "nc_cd_02_smoke";

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
