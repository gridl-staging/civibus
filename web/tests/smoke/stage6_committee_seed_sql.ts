// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { SMOKE_LIVE_API_BASE_URL, SMOKE_STAGE6_COMMITTEE_ID, SMOKE_STAGE6_COMMITTEE_CYCLE_LABEL, SMOKE_STAGE6_COMMITTEE_NAME, SMOKE_STAGE6_COMMITTEE_SUMMARY_ID, SMOKE_STAGE6_CURRENT_CYCLE_SUMMARY_ID, SMOKE_STAGE6_DATA_SOURCE_ID, SMOKE_STAGE6_FEC_CANDIDATE_ID, SMOKE_STAGE6_FEC_COMMITTEE_ID, SMOKE_STAGE6_LINKED_CANDIDATE_ID, SMOKE_STAGE6_LINKED_CANDIDATE_NAME, SMOKE_STAGE6_LINK_ID, SMOKE_STAGE6_SOURCE_RECORD_ID } from "./fixtures.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { runSmokeSeedSql, sqlLiteral, sqlUuid, type SmokeSeedCleanupCallback } from "./smoke_seed_helpers.ts";

// The past cycle the base seed writes a committee_summary row for, so the
// committee carries a real historical record alongside the current-cycle one the
// page selects by default.
//
// Read from the fixtures constant rather than duplicated as a literal, and read
// inside a function rather than at module scope: fixtures.ts re-exports this
// module's seed helper, so the two form an import cycle and a top-level read of a
// fixtures.ts constant lands in its temporal dead zone.
function stage6HistoryCycle(): number {
  return Number(SMOKE_STAGE6_COMMITTEE_CYCLE_LABEL);
}

export function buildStage6CommitteeCleanupSql(): string {
  return `
BEGIN;
DELETE FROM cf.candidate_committee_link
WHERE id = ${sqlUuid(SMOKE_STAGE6_LINK_ID, "SMOKE_STAGE6_LINK_ID")};
DELETE FROM cf.committee_summary
WHERE id IN (
  ${sqlUuid(SMOKE_STAGE6_COMMITTEE_SUMMARY_ID, "SMOKE_STAGE6_COMMITTEE_SUMMARY_ID")},
  ${sqlUuid(SMOKE_STAGE6_CURRENT_CYCLE_SUMMARY_ID, "SMOKE_STAGE6_CURRENT_CYCLE_SUMMARY_ID")}
);
DELETE FROM cf.candidate
WHERE id = ${sqlUuid(SMOKE_STAGE6_LINKED_CANDIDATE_ID, "SMOKE_STAGE6_LINKED_CANDIDATE_ID")}
OR fec_candidate_id = ${sqlLiteral(SMOKE_STAGE6_FEC_CANDIDATE_ID)};
DELETE FROM cf.committee
WHERE id = ${sqlUuid(SMOKE_STAGE6_COMMITTEE_ID, "SMOKE_STAGE6_COMMITTEE_ID")}
OR fec_committee_id = ${sqlLiteral(SMOKE_STAGE6_FEC_COMMITTEE_ID)};
DELETE FROM core.source_record
WHERE id = ${sqlUuid(SMOKE_STAGE6_SOURCE_RECORD_ID, "SMOKE_STAGE6_SOURCE_RECORD_ID")};
DELETE FROM core.data_source
WHERE id = ${sqlUuid(SMOKE_STAGE6_DATA_SOURCE_ID, "SMOKE_STAGE6_DATA_SOURCE_ID")};
COMMIT;
`;
}

export function buildStage6CommitteeSeedSql(): string {
  const cleanup = buildStage6CommitteeCleanupSql();
  return `
${cleanup}
BEGIN;
INSERT INTO core.data_source (id, domain, jurisdiction, name, source_url, source_format, license, update_frequency)
VALUES (
  ${sqlUuid(SMOKE_STAGE6_DATA_SOURCE_ID, "SMOKE_STAGE6_DATA_SOURCE_ID")},
  'campaign_finance',
  'federal/fec',
  'Stage 6 smoke FEC source',
  'https://example.org/stage6-smoke/fec',
  'csv',
  'public_domain',
  'weekly'
);
INSERT INTO core.source_record (id, data_source_id, source_record_key, source_url, raw_fields, pull_date, record_hash)
VALUES (
  ${sqlUuid(SMOKE_STAGE6_SOURCE_RECORD_ID, "SMOKE_STAGE6_SOURCE_RECORD_ID")},
  ${sqlUuid(SMOKE_STAGE6_DATA_SOURCE_ID, "SMOKE_STAGE6_DATA_SOURCE_ID")},
  'stage6-smoke-committee-summary',
  'https://example.org/stage6-smoke/committee-summary',
  '{"fec_committee_id":"${SMOKE_STAGE6_FEC_COMMITTEE_ID}","fec_candidate_id":"${SMOKE_STAGE6_FEC_CANDIDATE_ID}"}'::jsonb,
  '2026-06-01T12:00:00Z',
  'stage6-smoke-committee-summary-hash'
);
INSERT INTO cf.committee (
  id, fec_committee_id, name, source_record_id, committee_type, committee_designation,
  party, state, city, zip_code, treasurer_name
)
VALUES (
  ${sqlUuid(SMOKE_STAGE6_COMMITTEE_ID, "SMOKE_STAGE6_COMMITTEE_ID")},
  ${sqlLiteral(SMOKE_STAGE6_FEC_COMMITTEE_ID)},
  ${sqlLiteral(SMOKE_STAGE6_COMMITTEE_NAME)},
  ${sqlUuid(SMOKE_STAGE6_SOURCE_RECORD_ID, "SMOKE_STAGE6_SOURCE_RECORD_ID")},
  'H',
  'P',
  'REP',
  'LA',
  'Shreveport',
  '71101',
  'Stage 6 Treasurer'
);
INSERT INTO cf.candidate (
  id, fec_candidate_id, name, office, person_id, principal_committee_id, source_record_id,
  party, state, district, incumbent_challenge, total_receipts, total_disbursements,
  cash_on_hand, summary_coverage_end_date
)
VALUES (
  ${sqlUuid(SMOKE_STAGE6_LINKED_CANDIDATE_ID, "SMOKE_STAGE6_LINKED_CANDIDATE_ID")},
  ${sqlLiteral(SMOKE_STAGE6_FEC_CANDIDATE_ID)},
  ${sqlLiteral(SMOKE_STAGE6_LINKED_CANDIDATE_NAME)},
  'H',
  NULL,
  ${sqlUuid(SMOKE_STAGE6_COMMITTEE_ID, "SMOKE_STAGE6_COMMITTEE_ID")},
  ${sqlUuid(SMOKE_STAGE6_SOURCE_RECORD_ID, "SMOKE_STAGE6_SOURCE_RECORD_ID")},
  'REP',
  'LA',
  '04',
  'I',
  1250000.00,
  400000.00,
  850000.00,
  '2024-12-31'
);
INSERT INTO cf.candidate_committee_link (
  id, candidate_id, committee_id, designation, candidate_election_year, fec_election_year,
  valid_period, source_record_id
)
VALUES (
  ${sqlUuid(SMOKE_STAGE6_LINK_ID, "SMOKE_STAGE6_LINK_ID")},
  ${sqlUuid(SMOKE_STAGE6_LINKED_CANDIDATE_ID, "SMOKE_STAGE6_LINKED_CANDIDATE_ID")},
  ${sqlUuid(SMOKE_STAGE6_COMMITTEE_ID, "SMOKE_STAGE6_COMMITTEE_ID")},
  'P',
  2024,
  2024,
  '[2023-01-01,2100-01-01)'::daterange,
  ${sqlUuid(SMOKE_STAGE6_SOURCE_RECORD_ID, "SMOKE_STAGE6_SOURCE_RECORD_ID")}
);
INSERT INTO cf.committee_summary (
  id, committee_id, source_record_id, cycle, coverage_start_date, coverage_end_date,
  total_receipts, total_disbursements, cash_on_hand
)
VALUES (
  ${sqlUuid(SMOKE_STAGE6_COMMITTEE_SUMMARY_ID, "SMOKE_STAGE6_COMMITTEE_SUMMARY_ID")},
  ${sqlUuid(SMOKE_STAGE6_COMMITTEE_ID, "SMOKE_STAGE6_COMMITTEE_ID")},
  ${sqlUuid(SMOKE_STAGE6_SOURCE_RECORD_ID, "SMOKE_STAGE6_SOURCE_RECORD_ID")},
  ${stage6HistoryCycle()},
  '${stage6HistoryCycle() - 1}-01-01',
  '${stage6HistoryCycle()}-12-31',
  1250000.00,
  400000.00,
  850000.00
);
COMMIT;
`;
}

/**
 * The cycle the committee detail page will select when no cycle is requested.
 *
 * api/queries/campaign_finance.py resolves that as
 * max(SUPPORTED_COMMITTEE_SUMMARY_CYCLES) and reports the same tuple back as
 * `available_cycles`, so reading it from the API keeps one owner for the value.
 * Pinning a literal here is what went stale: the fixture seeded a 2024 summary,
 * the supported tuple grew a 2026 entry, and the default view silently fell back
 * to "derived from itemized transactions" with a $0.00 total.
 */
async function resolveDefaultCommitteeSummaryCycle(): Promise<number> {
  const response = await fetch(
    `${SMOKE_LIVE_API_BASE_URL}/v1/committees/${SMOKE_STAGE6_COMMITTEE_ID}/summary`
  );
  if (!response.ok) {
    throw new Error(
      `Stage 6 seed could not read available cycles: committee summary returned ${response.status}`
    );
  }
  const body = (await response.json()) as { available_cycles?: number[] };
  const cycles = body.available_cycles ?? [];
  if (cycles.length === 0) {
    // Never guess a cycle: a silent fallback would reseed at whatever literal we
    // picked and reintroduce exactly the staleness this function removes.
    throw new Error("Stage 6 seed could not read available cycles: response carried none");
  }
  return Math.max(...cycles);
}

function buildStage6CurrentCycleSummarySql(cycle: number): string {
  return `
INSERT INTO cf.committee_summary (
  id, committee_id, source_record_id, cycle, coverage_start_date, coverage_end_date,
  total_receipts, total_disbursements, cash_on_hand
)
VALUES (
  ${sqlUuid(SMOKE_STAGE6_CURRENT_CYCLE_SUMMARY_ID, "SMOKE_STAGE6_CURRENT_CYCLE_SUMMARY_ID")},
  ${sqlUuid(SMOKE_STAGE6_COMMITTEE_ID, "SMOKE_STAGE6_COMMITTEE_ID")},
  ${sqlUuid(SMOKE_STAGE6_SOURCE_RECORD_ID, "SMOKE_STAGE6_SOURCE_RECORD_ID")},
  ${cycle},
  '${cycle - 1}-01-01',
  '${cycle}-12-31',
  1250000.00,
  400000.00,
  850000.00
);
`;
}

export async function seedLiveStage6CommitteeSmoke(): Promise<SmokeSeedCleanupCallback> {
  await runSmokeSeedSql(buildStage6CommitteeSeedSql());
  // Two round trips on purpose: the committee has to exist before the summary
  // endpoint will report which cycles the API supports.
  const defaultCycle = await resolveDefaultCommitteeSummaryCycle();
  if (defaultCycle !== stage6HistoryCycle()) {
    await runSmokeSeedSql(buildStage6CurrentCycleSummarySql(defaultCycle));
  }
  return async () => {
    await runSmokeSeedSql(buildStage6CommitteeCleanupSql());
  };
}
