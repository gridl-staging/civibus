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

function buildDonorSearchResult(params: { id: string; contributorName: string; totalAmount: string }): unknown {
  return {
    id: params.id,
    contributor_name: params.contributorName,
    contributor_employer: SMOKE_DONOR_LOOKUP_SEED_EMPLOYER,
    contributor_occupation: "Engineer",
    contributor_city: "Durham",
    contributor_state: "NC",
    normalized_zip5: SMOKE_DONOR_LOOKUP_SEED_ZIP5,
    total_amount: params.totalAmount,
    transaction_count: 1,
    latest_transaction_date: "2024-07-15",
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
        transaction_count: 1
      }
    ],
    sources: [
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "Campaign Finance API Source donor-search-fixture",
        data_source_url: "https://example.org/campaign-finance-source",
        source_record_key: `${params.id}:source`,
        record_url: "https://example.org/fec/donor-search/current",
        pull_date: "2026-07-09T12:00:00Z"
      }
    ]
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
            totalAmount: "250.00"
          })
        ]
      : [];

  return {
    query,
    by,
    limit,
    offset,
    results: allResults.slice(offset, offset + limit)
  };
}
