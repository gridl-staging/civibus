// @ts-expect-error Smoke fixtures run under Node ESM and import the TS module directly.
import { resolveSmokeApiPort } from "../../src/lib/server/api/smoke-port.ts";
// @ts-expect-error Smoke fixtures run under Node ESM and import the TS module directly.
import { APP_SHELL } from "../../src/lib/config/app.ts";
// @ts-expect-error Smoke fixtures run under Node ESM and import the TS module directly.
import { DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME, DONOR_LOOKUP_SEED_EMPLOYER, DONOR_LOOKUP_SEED_PERSON_ID, DONOR_LOOKUP_SEED_TOTAL_AMOUNT, DONOR_LOOKUP_SEED_ZIP5 } from "../../src/lib/donors/fixture.ts";
// @ts-expect-error Smoke fixtures run under Node ESM and import the TS module directly.
import { COMMITTEE_SUMMARY_SOURCE_LABELS, buildCommitteeItemizedCoverageNote } from "../../src/lib/campaign-finance-detail/summary-source.ts";

export const SMOKE_API_HOST = "127.0.0.1";
export const SMOKE_API_PORT = resolveSmokeApiPort(process.env);
export const SMOKE_API_BASE_URL = `http://${SMOKE_API_HOST}:${SMOKE_API_PORT}`;

// Live-backed Stage 7 smoke runs override these IDs/slugs via env vars
// (SMOKE_PERSON_ID, SMOKE_CONTEST_ID, SMOKE_OFFICE_ID, SMOKE_COMMITTEE_SLUG,
// SMOKE_CANDIDATE_ID) so the same constants point at real DB records when
// SMOKE_USE_LIVE_API=1 and at synthetic fixture records otherwise. Do not
// fork LIVE_* variants — operators set env vars for live mode.
export const SMOKE_USE_LIVE_API = process.env.SMOKE_USE_LIVE_API === "1";
export const SMOKE_PERSON_ID = process.env.SMOKE_PERSON_ID ?? "11111111-1111-4111-8111-111111111111";
export const SMOKE_PERSON_NO_PORTRAIT_ID = "11111111-1111-4111-8111-111111111112";
export const SMOKE_PERSON_MISSING_PORTRAIT_FIELD_ID = "11111111-1111-4111-8111-111111111113";
export const SMOKE_ROSTER_DURHAM_PERSON_ID = "11111111-1111-4111-8111-1111111111d0";
export const SMOKE_ROSTER_NC_HOUSE_PERSON_ID = "11111111-1111-4111-8111-1111111111d1";
export const SMOKE_ROSTER_DURHAM_PERSON_CANONICAL_NAME = "Javiera Caballero";
export const SMOKE_ROSTER_NC_HOUSE_PERSON_CANONICAL_NAME = "Pricey Harrison";
export const SMOKE_ROSTER_DURHAM_PORTRAIT_URL =
  "https://www.durhamnc.gov/ImageRepository/Document?documentID=53769&thumbnailSize=2";
export const SMOKE_ROSTER_NC_HOUSE_PORTRAIT_URL = "https://www.ncleg.gov/Members/MemberImage/H/76/Low";
export const SMOKE_ORG_ID = "22222222-2222-4222-8222-222222222222";
export const SMOKE_FILING_ID = "33333333-3333-4333-8333-333333333333";
export const SMOKE_COMMITTEE_ID = process.env.SMOKE_COMMITTEE_ID ?? "44444444-4444-4444-8444-444444444444";
export const SMOKE_CANDIDATE_ID = process.env.SMOKE_CANDIDATE_ID ?? "55555555-5555-4555-8555-555555555555";
export const SMOKE_OUT_OF_CYCLE_CANDIDATE_ID = "56565656-5656-4565-8565-565656565656";
export const SMOKE_PROPERTY_ID = "66666666-6666-4666-8666-666666666666";
export const SMOKE_COMMITTEE_SLUG = process.env.SMOKE_COMMITTEE_SLUG ?? "citizens-for-civibus";
export const SMOKE_CANDIDATE_SLUG = "pat-candidate";
export const SMOKE_OUT_OF_CYCLE_CANDIDATE_SLUG = "candidate-earlier-cycle-total";
export const SMOKE_EMPTY_CANDIDATE_SLUG = "candidate-empty";
export const SMOKE_LOADED_ZERO_CANDIDATE_SLUG = "candidate-loaded-zero";
export const SMOKE_COLLIDING_COMMITTEE_SLUG = "shared-committee";
export const SMOKE_COLLIDING_CANDIDATE_SLUG = "shared-candidate";
export const SMOKE_COLLIDING_COMMITTEE_ID = "77777777-7777-4777-8777-777777777777";
export const SMOKE_COLLIDING_CANDIDATE_ID = "88888888-8888-4888-8888-888888888888";
export const SMOKE_EMPTY_COMMITTEE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const SMOKE_EMPTY_CANDIDATE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
export const SMOKE_DEVIANT_CANDIDATE_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
export const SMOKE_LOADED_ZERO_CANDIDATE_ID = "edededed-eded-4ede-8ede-edededededed";
export const SMOKE_BACKEND_FAILURE_CANDIDATE_ID = "fdfdfdfd-fdfd-4fdf-8fdf-fdfdfdfdfdfd";
export const SMOKE_AL_CANDIDATE_ID = "abababab-abab-4aba-8aba-abababababab";
export const SMOKE_GA_CANDIDATE_ID = "cdcdcdcd-cdcd-4cdc-8cdc-cdcdcdcdcdcd";
export const SMOKE_EMPTY_PROPERTY_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
export const SMOKE_OFFICE_ID = process.env.SMOKE_OFFICE_ID ?? "ee111111-1111-4111-8111-111111111111";
export const SMOKE_EMPTY_OFFICE_ID = "ee222222-2222-4222-8222-222222222222";
export const SMOKE_OFFICE_OFFICEHOLDER_ID = "ff111111-1111-4111-8111-111111111111";
export const SMOKE_PHL_COMMITTEE_ID = "12121212-1212-4121-8121-121212121212";
export const SMOKE_NC_SHOWCASE_STATE_CODE = "NC";
export const SMOKE_NC_SHOWCASE_COUNTY_SLUG = "wake";
export const SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME = "nc_county_wake";
export const SMOKE_NC_SHOWCASE_DISTRICT_DIVISION_NAME = "nc_cd_01";
export const SMOKE_NC_SHOWCASE_COUNTY_HEADING = "Wake County, NC";
export const SMOKE_NC_SHOWCASE_DONOR_TOTAL = "$1,234.56";
export const SMOKE_NC_SHOWCASE_RECIPIENT_NAME = "Wake County Future Fund";
export const SMOKE_NC_SHOWCASE_TRUST_SOURCE_NAME = "NC Campaign Finance (campaign_finance/state/nc)";

export const SMOKE_SEARCH_QUERY = "civ";
export const SMOKE_SEARCH_RESULT_NAME = "Civibus Action Org";
export const SMOKE_SEARCH_VALIDATION_QUERY = "zz";
export const SMOKE_SEARCH_VALIDATION_MESSAGE = "query.q: Synthetic validation failure for smoke coverage";
export const SMOKE_SEARCH_SLOW_QUERY = "slow";
// civibus-x9d (2026-08-20): candidate search rows are cf.candidate records
// routed to /candidate/[id], so the fixture row must point at the smoke
// candidate RECORD (SMOKE_CANDIDATE_ID / "Pat Candidate"), not a person row.
// The old "Jane Doe" row carried a person UUID under a candidate badge — the
// superseded pre-x9d contract — which routed to a page the fixture backend
// cannot serve under the new routing.
export const SMOKE_SEARCH_CANDIDATE_QUERY = "pat";
// Must equal the fixture candidate record's presented name (SMOKE_CANDIDATE_NAME,
// declared below; string duplicated here only because const declaration order
// forbids the forward reference).
export const SMOKE_SEARCH_CANDIDATE_RESULT_NAME = "Pat Candidate";
export const SMOKE_SEARCH_CONTEST_QUERY = "senate";
export const SMOKE_SEARCH_CONTEST_RESULT_NAME = "2026 NC Senate General";
export const SMOKE_SEARCH_EMPTY_TITLE = "Search | Civibus";
export const SMOKE_SEARCH_EMPTY_DESCRIPTION =
  "Search people, organizations, committees, candidates, offices, and contests across campaign-finance and civic records.";
export const SMOKE_SEARCH_TITLE = "civ (1 result) | Search | Civibus";
export const SMOKE_SEARCH_DESCRIPTION = '1 result for "civ" across Civibus records.';
export const SMOKE_HOME_TITLE = APP_SHELL.staticRoutes.home.title;
export const SMOKE_HOME_DESCRIPTION = APP_SHELL.staticRoutes.home.description;
export const SMOKE_HOME_HEADING = APP_SHELL.landing.heading;
export const SMOKE_HOME_BODY = APP_SHELL.landing.body;
export const SMOKE_HOME_FEDERAL_SCOPE_PHRASE = "543 elected federal";
export const SMOKE_HOME_PRIMARY_ACTION = APP_SHELL.landing.cta.label;
export const SMOKE_HOME_PRIMARY_ACTION_HREF = APP_SHELL.landing.cta.href;
export const SMOKE_HOME_SEARCH_ACTION = APP_SHELL.landing.actions[0].label;
export const SMOKE_HOME_SEARCH_ACTION_HREF = APP_SHELL.landing.actions[0].href;
export const SMOKE_HOME_METHODOLOGY_ACTION = APP_SHELL.landing.actions[1].label;
export const SMOKE_HOME_METHODOLOGY_ACTION_HREF = APP_SHELL.landing.actions[1].href;
export const SMOKE_HOME_ACTION_LABELS = [
  SMOKE_HOME_PRIMARY_ACTION,
  SMOKE_HOME_SEARCH_ACTION,
  SMOKE_HOME_METHODOLOGY_ACTION
] as const;
export const SMOKE_HOME_COVERAGE_HEADING = APP_SHELL.landing.coverageHeading;
export const SMOKE_HOME_COVERAGE_SUMMARY = APP_SHELL.landing.coverageSummary;
export const SMOKE_HOME_SCOPE_LINK = "Read methodology.";
export const SMOKE_HOME_SCOPE_LINK_HREF = APP_SHELL.landing.actions[1].href;
export const SMOKE_HOME_FORBIDDEN_STATE_ACTION = ["Browse coverage", "by state"].join(" ");
export const SMOKE_HOME_FORBIDDEN_SUPPORTED_STATE = "North Carolina";
export const SMOKE_HOME_FORBIDDEN_UNSUPPORTED_STATE = "Arkansas";
export const SMOKE_HOME_FORBIDDEN_UNSUPPORTED_LABEL = APP_SHELL.landing.mapUnsupportedLabel;
export const SMOKE_HOME_FORBIDDEN_WARNING_STATE = "Minnesota";
export const SMOKE_HOME_FORBIDDEN_WARNING_TEXT = "Quarterly bulk only; refresh cadence below weekly target.";
export const SMOKE_HOME_FORBIDDEN_CANDIDATE_ACTION = "Browse Candidates";
export const SMOKE_HOME_FORBIDDEN_COMMITTEE_ACTION = "Browse Committees";
export const SMOKE_STATE_DETAIL_SUPPORTED_CODE = "NC";
export const SMOKE_STATE_DETAIL_SUPPORTED_NAME = "North Carolina";
export const SMOKE_STATE_DETAIL_RETIRED_HEADING = "State campaign finance is outside federal-first v1";
export const SMOKE_STATE_DETAIL_RETIRED_MESSAGE =
  "Civibus v1 is focused on federal officials, candidates, committees, and independent expenditures.";
export const SMOKE_STATE_DETAIL_WARNING_STATE_NAME = "Minnesota";
export const SMOKE_STATE_DETAIL_UNSUPPORTED_CODE = "AR";
export const SMOKE_STATE_DETAIL_WARNING_CODE = "MN";
export const SMOKE_STATE_DETAIL_NO_IE_CODE = "LA";
export const SMOKE_STATE_DETAIL_UNSUPPORTED_MESSAGE =
  "Coverage is not currently supported for this state.";
export const SMOKE_STATE_DETAIL_WARNING_TEXT = "Quarterly bulk only; refresh cadence below weekly target.";
export const SMOKE_STATE_DETAIL_IE_CAVEAT = "Independent expenditure data is incomplete for this state.";
export const SMOKE_STATE_DETAIL_UNSUPPORTED_LABEL = "Unsupported";
export const SMOKE_STATE_DETAIL_INCOMPLETE_LABEL = "Incomplete";
export const SMOKE_STATE_DETAIL_INCOMPLETE_MAP_LABEL = "Coverage incomplete";
export const SMOKE_STATE_DETAIL_TOP_CANDIDATE_NAME = "Pat Candidate";
export const SMOKE_STATE_DETAIL_TOP_CANDIDATE_TOTAL = "$250.00";
export const SMOKE_STATE_DETAIL_TOP_COMMITTEE_NAME = "Citizens for Civibus";
export const SMOKE_STATE_DETAIL_TOP_COMMITTEE_TOTAL = "$125.00";
export const SMOKE_STATE_DETAIL_TOP_IE_SPENDER_NAME = "Super PAC Alpha";
export const SMOKE_STATE_DETAIL_TOP_IE_SPENDER_TOTAL = "$15,000.00";
// Methodology smoke expectations are DERIVED from the copy owner, never retyped.
// web/src/routes/methodology/+page.svelte renders APP_SHELL.methodology.sections
// verbatim (heading, then each paragraph), so deriving here makes it impossible
// for these fixtures to assert text the page no longer renders.
//
// Why this matters: these constants were previously hardcoded copies. The
// 2026-08-15 methodology rewrite (d8e6a514d) replaced the page copy but left the
// duplicates here pinned to deleted text, and the resulting smoke failure rolled
// back the 2026-08-17 production deploy. A hardcoded second copy of copy is the
// defect; derivation is the fix.
//
// Look the section up by testId, not array index: the screen spec
// (docs/reference/screen_specs/methodology.md "## Disclosure contract") pins the
// four test ids, so an id is a stable contract while position is not.
const methodologyFreshnessSection = APP_SHELL.methodology.sections.find(
  (section) => section.testId === "methodology-freshness"
);
if (!methodologyFreshnessSection) {
  // Fail loudly at import time rather than exporting undefined, which would make
  // every consuming assertion silently vacuous.
  throw new Error("APP_SHELL.methodology has no methodology-freshness section");
}

export const SMOKE_METHODOLOGY_TITLE = APP_SHELL.staticRoutes.methodology.title;
export const SMOKE_METHODOLOGY_DESCRIPTION = APP_SHELL.staticRoutes.methodology.description;
export const SMOKE_METHODOLOGY_SECTION_HEADING = methodologyFreshnessSection.heading;
export const SMOKE_METHODOLOGY_SECTION_BODY = methodologyFreshnessSection.paragraphs[0];
export const SMOKE_SHELL_NAV_HOME = "Home";
export const SMOKE_SHELL_NAV_SEARCH = "Search";
export const SMOKE_SHELL_NAV_CANDIDATES = "Candidates";
export const SMOKE_SHELL_NAV_COMMITTEES = "Committees";
export const SMOKE_SHELL_NAV_CONGRESS = "Congress";
export const SMOKE_SHELL_NAV_DEVELOPERS = "Developers";
export const SMOKE_SHELL_NAV_METHODOLOGY = "Methodology";
export const SMOKE_SHELL_PRIMARY_NAV_LABELS = [
  SMOKE_SHELL_NAV_HOME,
  SMOKE_SHELL_NAV_SEARCH,
  SMOKE_SHELL_NAV_CANDIDATES,
  SMOKE_SHELL_NAV_COMMITTEES,
  SMOKE_SHELL_NAV_CONGRESS,
  SMOKE_SHELL_NAV_DEVELOPERS,
  SMOKE_SHELL_NAV_METHODOLOGY
] as const;
export const SMOKE_DONOR_LOOKUP_QUERY = "Jane";
export const SMOKE_DONOR_LOOKUP_HEADING = "Donor Lookup";
export const SMOKE_DONOR_LOOKUP_SCOPE_NOTE =
  "Results cover itemized contributions to committees of current federal officeholders only. Unitemized (<$200) contributions are not included.";
export const SMOKE_DONOR_LOOKUP_RESULT_COUNT = "Showing donors 1-1.";
export const SMOKE_DONOR_LOOKUP_RECIPIENT_NAME = "Alpha Officeholder";
export const SMOKE_DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME = DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME;
export const SMOKE_DONOR_LOOKUP_SEED_EMPLOYER = DONOR_LOOKUP_SEED_EMPLOYER;
export const SMOKE_DONOR_LOOKUP_SEED_ZIP5 = DONOR_LOOKUP_SEED_ZIP5;
export const SMOKE_DONOR_LOOKUP_SEED_PERSON_ID = DONOR_LOOKUP_SEED_PERSON_ID;
export const SMOKE_DONOR_LOOKUP_SEED_TOTAL_AMOUNT = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD"
}).format(Number(DONOR_LOOKUP_SEED_TOTAL_AMOUNT));
export const SMOKE_COVERAGE_ROUTE_PATH = "/coverage";
export const SMOKE_CALENDAR_ROUTE_PATH = "/calendar";
export const SMOKE_DATA_SOURCES_ROUTE_PATH = "/data-sources";
export const SMOKE_ELECTION_DATE = "2026-11-03";
export const SMOKE_ELECTION_ROUTE_PATH = `/election/${SMOKE_ELECTION_DATE}`;
export const SMOKE_COVERAGE_HEADING = "Coverage registry";
export const SMOKE_CALENDAR_HEADING = "Election calendar";
export const SMOKE_DATA_SOURCES_HEADING = "Data sources";
export const SMOKE_ELECTION_HEADING = `Election ${SMOKE_ELECTION_DATE}`;
export const SMOKE_COVERAGE_DOMAIN = "campaign_finance";
export const SMOKE_COVERAGE_JURISDICTION = "state/NC";
export const SMOKE_DATA_SOURCE_NAME = "NC Campaign Finance";
export const SMOKE_COVERAGE_TITLE = "Coverage Registry | Civibus";
export const SMOKE_COVERAGE_DESCRIPTION =
  "Review runtime coverage registry rows grouped by domain and jurisdiction with latest pull timestamps.";
export const SMOKE_CALENDAR_TITLE = "Election Calendar | Civibus";
export const SMOKE_CALENDAR_DESCRIPTION =
  "Track upcoming elections with contest-level counts and linked civic coverage across supported jurisdictions.";
export const SMOKE_DATA_SOURCES_TITLE = "Data Sources | Civibus";
export const SMOKE_DATA_SOURCES_DESCRIPTION =
  "Inspect runtime data-source metadata, pull status, and source-record pointers from the backend registry.";
export const SMOKE_ELECTION_TITLE = `${SMOKE_ELECTION_HEADING} | Civibus`;
export const SMOKE_ELECTION_DESCRIPTION =
  `Election results and contest overview for ${SMOKE_ELECTION_DATE} across supported jurisdictions.`;
export const SMOKE_PUBLIC_API_HEADING = "Public API";
export const SMOKE_PUBLIC_API_ENDPOINTS = [
  "GET /api/public/v1/federal/officials",
  "GET /api/public/v1/federal/officials/{person_id}/money",
  "GET /api/public/v1/federal/officials/{person_id}/contributors",
  "GET /api/public/v1/federal/officials/{person_id}/employers",
  "GET /api/public/v1/federal/export.json",
  "GET /api/public/v1/federal/export.csv",
  "GET /api/public/v1/federal/metadata"
] as const;
export const SMOKE_PUBLIC_API_MIGRATION_HEADING = "OpenSecrets and ProPublica migration mapping";
export const SMOKE_PUBLIC_API_MIGRATION_COLUMNS = [
  "Source API and endpoint/product",
  "Civibus equivalent",
  "Honest delta"
] as const;
export const SMOKE_PUBLIC_API_MIGRATION_ROWS = [
  {
    source: "ProPublica Congress API members",
    civibusEquivalent: SMOKE_PUBLIC_API_ENDPOINTS[0],
    delta: "Current federal officeholders only; no historical membership or legislative activity."
  },
  {
    source: "OpenSecrets API candSummary",
    civibusEquivalent: SMOKE_PUBLIC_API_ENDPOINTS[1],
    delta: "FEC summary totals and Schedule E support or opposition, keyed by Civibus person_id."
  },
  {
    source: "OpenSecrets API candContrib",
    civibusEquivalent: SMOKE_PUBLIC_API_ENDPOINTS[2],
    delta: "Aggregated contributor names from itemized FEC receipts; donor identities remain unresolved."
  },
  {
    source: "OpenSecrets API candIndustry",
    civibusEquivalent: SMOKE_PUBLIC_API_ENDPOINTS[3],
    delta: "Employer rollups disclose sparse industry classification and do not reproduce OpenSecrets categories."
  },
  {
    source: "OpenSecrets bulk candidate summaries (JSON)",
    civibusEquivalent: SMOKE_PUBLIC_API_ENDPOINTS[4],
    delta: "Current federal officeholders with FEC summaries and Schedule E totals; not a full OpenSecrets bulk mirror."
  },
  {
    source: "OpenSecrets bulk candidate summaries (CSV)",
    civibusEquivalent: SMOKE_PUBLIC_API_ENDPOINTS[5],
    delta: "The same bounded Civibus export in spreadsheet form with source URLs."
  },
  {
    source: "ProPublica Congress API roll-call votes",
    civibusEquivalent: "No Civibus equivalent yet",
    delta: "Civibus does not currently publish roll-call votes or voting positions."
  }
] as const;
export const SMOKE_PUBLIC_API_STABILITY_HEADING = "Stability, freshness, and limits";
export const SMOKE_PUBLIC_API_STABILITY_COPY =
  "Endpoint schemas are the stable client contract. Read the metadata endpoint for live source freshness, coverage qualifications, and the effective rate-limit policy.";
export const SMOKE_PUBLIC_API_METADATA_REFERENCE = SMOKE_PUBLIC_API_ENDPOINTS[6];
export const SMOKE_PUBLIC_API_CACHE_CONTRACT = "Cache-Control: public, max-age=900";
export const SMOKE_PUBLIC_API_SAMPLE_JSON_VALUE = '"office_name": "U.S. House NC-01"';
export const SMOKE_PUBLIC_API_CONTRIBUTOR_CURL =
  "/api/public/v1/federal/officials/11111111-1111-1111-1111-111111111111/contributors";
export const SMOKE_PUBLIC_API_EMPLOYER_CURL =
  "/api/public/v1/federal/officials/11111111-1111-1111-1111-111111111111/employers";
export const SMOKE_PUBLIC_API_CONTRIBUTOR_SAMPLE_NAME = '"name": "Sample Contributor"';
export const SMOKE_PUBLIC_API_CONTRIBUTOR_SAMPLE_AMOUNT = '"total_amount": "5000.00"';
export const SMOKE_PUBLIC_API_EMPLOYER_UNKNOWN_BUCKET = '"industry": "UNKNOWN_INDUSTRY"';
export const SMOKE_PUBLIC_API_EMPLOYER_COVERAGE_FIELD = '"sampled_coverage_percentage": "5.843340"';
export const SMOKE_PUBLIC_API_CSV_HEADER =
  "person_id,person_name,has_fec_money,candidate_id,total_raised,total_spent,net,cash_on_hand,summary_source,ie_support_total,ie_oppose_total,ie_support_count,ie_oppose_count,source_urls";
export const SMOKE_PUBLIC_API_REFERENCE_LINKS = ["/api/openapi.json", "/api/docs", "/api/redoc"] as const;
export const SMOKE_PUBLIC_API_FOOTER_LINK = "Public API";
export const SMOKE_PUBLIC_API_ROUTE_PATH = "/developers";

export const SMOKE_PERSON_CANONICAL_NAME = "Jane Doe";
export const SMOKE_PERSON_NO_PORTRAIT_CANONICAL_NAME = "Jordan No Portrait";
export const SMOKE_PERSON_MISSING_PORTRAIT_CANONICAL_NAME = "Avery Missing Portrait";
export const SMOKE_PERSON_TITLE = "Jane Doe | Person | Civibus";
export const SMOKE_PERSON_DESCRIPTION =
  "Person profile with 1 identifier and source-linked records.";
export const SMOKE_ENTITY_PORTRAIT_INITIALS_TEST_ID = "entity-portrait-initials";
export const SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID = "entity-portrait-image";
export const SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID = "entity-portrait-silhouette";

export const SMOKE_ORG_CANONICAL_NAME = "Civibus Action Org";
export const SMOKE_ORG_TITLE = "Civibus Action Org | Organization | Civibus";
export const SMOKE_ORG_DESCRIPTION =
  "Organization profile with 1 identifier and source-linked records.";

export const SMOKE_COMMITTEE_NAME = "Citizens for Civibus";
export const SMOKE_PHL_COMMITTEE_NAME = "Philadelphia Transit Neighbors";
export const SMOKE_CANDIDATE_NAME = "Pat Candidate";
export const SMOKE_OUT_OF_CYCLE_CANDIDATE_NAME = "Candidate Earlier Cycle Total";
export const SMOKE_COMMITTEE_TITLE = "Citizens for Civibus | Committee | Civibus";
export const SMOKE_PHL_COMMITTEE_TITLE = "Philadelphia Transit Neighbors | Committee | Civibus";
export const SMOKE_COMMITTEE_DESCRIPTION = "Committee profile from campaign-finance records.";
export const SMOKE_PHL_COMMITTEE_DESCRIPTION = "Committee profile from campaign-finance records.";
export const SMOKE_COMMITTEES_TITLE = "Committees | Civibus";
export const SMOKE_COMMITTEES_DESCRIPTION = "Campaign-finance committees with server-rendered pagination.";
export const SMOKE_CANDIDATE_LIST_CONTEXT = "DEM · H · NC-01";
export const SMOKE_COMMITTEE_LIST_CONTEXT = "Q · DEM · NC";
export const SMOKE_CANDIDATES_FIRST_PAGE_LABEL = "Showing 1–1";
export const SMOKE_CANDIDATES_SECOND_PAGE_LABEL = "Showing 2–2";
export const SMOKE_COMMITTEES_FIRST_PAGE_LABEL = "Showing 1–1";
export const SMOKE_COMMITTEES_SECOND_PAGE_LABEL = "Showing 2–2";
export const SMOKE_COMMITTEE_TOTAL_RAISED = "$125.00";
export const SMOKE_COMMITTEE_TOTAL_SPENT = "$40.00";
export const SMOKE_COMMITTEE_NET_TOTAL = "$85.00";
export const SMOKE_COMMITTEE_FILING_ROW_LABEL = "Q1 Filing (F3N)";
export const SMOKE_COMMITTEE_SECOND_FILING_ROW_LABEL = "Q2 Filing (F3N)";
export const SMOKE_COMMITTEE_FILING_SUMMARY_EMPTY_STATE = "No filing-period fundraising data available.";
export const SMOKE_COMMITTEE_CASH_TREND_COVERAGE_META =
  "2026 cycle, coverage through June 30, 2026. Unit: dollars";
export const SMOKE_COMMITTEE_CASH_TREND_FIRST_PERIOD = "March 31, 2026";
export const SMOKE_COMMITTEE_CASH_TREND_SECOND_PERIOD = "June 30, 2026";
export const SMOKE_COMMITTEE_CASH_TREND_FIRST_BALANCE = "$125.00";
export const SMOKE_COMMITTEE_CASH_TREND_LATEST_BALANCE = "$250.50";
export const SMOKE_COMMITTEE_CASH_TREND_LATEST_COPY =
  "Cash on hand is $250.50 at the latest filing period in the 2026 cycle.";
export const SMOKE_COMMITTEE_CASH_TREND_MISSING_INTERVAL =
  "Missing source coverage before this filing period.";
export const SMOKE_COMMITTEE_CASH_TREND_NO_MISSING_INTERVAL = "No explicit missing interval.";
export const SMOKE_COMMITTEE_ORG_LINK_TEXT = `Organization record (${SMOKE_ORG_ID})`;
export const SMOKE_COMMITTEE_CONTRIBUTOR_PERSON_LINK_TEXT = "View contributor person record";
export const SMOKE_COMMITTEE_CONTRIBUTOR_ORG_LINK_TEXT = "View contributor organization record";
export const SMOKE_COMMITTEE_RECIPIENT_CANDIDATE_LINK_TEXT = "View recipient candidate record";
export const SMOKE_COMMITTEE_RECIPIENT_COMMITTEE_LINK_TEXT = "View recipient committee record";

// Deterministic filing-pagination fixtures (Stage 4 browser proof). Two fixture-only
// committees exercise the client-paginated filing table without a server round trip:
// `SMOKE_FILINGS_PAGED_COMMITTEE_ID` fetches 30 filings (a full page 1 followed by a
// short page 2), while `SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID` fetches the full 200-row
// recent window over a much larger all-time count so the label separates the two.
// The row and label text below is the expected rendered output; smoke_fixtures_ssot.test.ts
// re-derives it from the real presenter so these constants cannot drift from page math.
export const SMOKE_FILINGS_PAGED_COMMITTEE_ID = "45454545-4545-4545-8545-454545454545";
export const SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID = "46464646-4646-4646-8646-464646464646";
export const SMOKE_FILINGS_PAGED_COMMITTEE_NAME = "Filing Pagination Committee";
export const SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_NAME = "Filing High-Total Committee";
export const SMOKE_FILINGS_PAGE_1_FIRST_ROW_LABEL = "Filing 01 (F3N)";
export const SMOKE_FILINGS_PAGE_1_LAST_ROW_LABEL = "Filing 25 (F3N)";
export const SMOKE_FILINGS_PAGE_2_FIRST_ROW_LABEL = "Filing 26 (F3N)";
export const SMOKE_FILINGS_PAGE_2_LAST_ROW_LABEL = "Filing 30 (F3N)";
export const SMOKE_FILINGS_PAGE_1_LABEL = "Showing 1–25 of 30 most recent · 30 total filings";
export const SMOKE_FILINGS_PAGE_2_LABEL = "Showing 26–30 of 30 most recent · 30 total filings";
export const SMOKE_FILINGS_HIGH_TOTAL_LABEL =
  "Showing 1–25 of 200 most recent · 220,706 total filings";

// The five committee detail bundle subresource counters exposed by the fixture backend's
// /_smoke/request-counts seam. The pagination smoke test asserts every key is present so a
// dropped or renamed counter fails the no-refetch proof closed instead of reading as zero.
export const SMOKE_COMMITTEE_REQUEST_COUNTER_KEYS = [
  "detail",
  "summary",
  "filings_summary",
  "independent_expenditures_made",
  "transactions"
] as const;

/**
 * Resets the fixture backend's per-committee request-count diagnostics. Lives here (not in a
 * spec) because API calls belong to the fixtures owner. Throws — fail closed — on a non-ok
 * response so the smoke test cannot silently proceed against stale counters.
 */
export async function resetSmokeCommitteeRequestCounts(request: {
  get: (url: string) => Promise<{ ok: () => boolean; status: () => number }>;
}): Promise<void> {
  const response = await request.get(`${SMOKE_API_BASE_URL}/_smoke/request-counts/reset`);
  if (!response.ok()) {
    throw new Error(`request-counts reset failed with status ${response.status()}`);
  }
}

/** Reads the fixture backend's per-committee subresource request counts. Throws on non-ok. */
export async function fetchSmokeCommitteeRequestCounts(
  request: {
    get: (url: string) => Promise<{
      ok: () => boolean;
      status: () => number;
      json: () => Promise<{ counts: Record<string, number> }>;
    }>;
  },
  committeeId: string
): Promise<Record<string, number>> {
  const response = await request.get(
    `${SMOKE_API_BASE_URL}/_smoke/request-counts?committee_id=${committeeId}`
  );
  if (!response.ok()) {
    throw new Error(`request-counts fetch failed with status ${response.status()}`);
  }
  const body = await response.json();
  return body.counts;
}
export const SMOKE_CANDIDATE_TITLE = "Pat Candidate | Candidate | Civibus";
export const SMOKE_OUT_OF_CYCLE_CANDIDATE_TITLE =
  "Candidate Earlier Cycle Total | Candidate | Civibus";
export const SMOKE_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";
export const SMOKE_CANDIDATES_TITLE = "Candidates | Civibus";
export const SMOKE_CANDIDATES_DESCRIPTION = "Campaign-finance candidates with server-rendered pagination.";
export const SMOKE_CANDIDATE_TOTAL_RAISED = "$250.00";
export const SMOKE_CANDIDATE_TOTAL_SPENT = "$80.00";
export const SMOKE_CANDIDATE_NET_TOTAL = "$170.00";
export const SMOKE_CANDIDATE_DATA_THROUGH = "2026-03-19";
export const SMOKE_CANDIDATE_CASH_ON_HAND = "$125.00";
export const SMOKE_CANDIDATE_SELECTED_CYCLE = "2026";
export const SMOKE_CANDIDATE_COVERAGE_THROUGH = "2026-12-31";
export const SMOKE_CANDIDATE_PERSON_LINK_TEXT = `Person record (${SMOKE_PERSON_ID})`;
export const SMOKE_CANDIDATE_COMMITTEE_LINK_TEXT = `Committee record (${SMOKE_COMMITTEE_ID})`;
export const SMOKE_EMPTY_COMMITTEE_TITLE = "Committee Empty | Committee | Civibus";
export const SMOKE_EMPTY_COMMITTEE_DESCRIPTION = "Committee profile from campaign-finance records.";
export const SMOKE_EMPTY_CANDIDATE_TITLE = "Candidate Empty | Candidate | Civibus";
export const SMOKE_EMPTY_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";
export const SMOKE_LOADED_ZERO_CANDIDATE_TITLE = "Candidate Loaded Zero | Candidate | Civibus";
export const SMOKE_BACKEND_FAILURE_CANDIDATE_TITLE = "Candidate Backend Failure | Candidate | Civibus";
export const SMOKE_DEVIANT_CANDIDATE_TITLE = "Candidate Deviant | Candidate | Civibus";
export const SMOKE_DEVIANT_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";
export const SMOKE_AUDITED_MALFORMED_CANDIDATE_ID = "99999999-9999-4999-8999-999999999999";
export const SMOKE_AUDITED_MALFORMED_CANDIDATE_RAW_NAME = "212 N HALF  W. JOHN, RODNEY HOWARD MR.";
export const SMOKE_AUDITED_MALFORMED_CANDIDATE_SOURCE_URL =
  "https://www.fec.gov/data/candidate/H0TX05005/";
export const SMOKE_AUDITED_MALFORMED_CANDIDATE_TITLE = "Candidate record | Civibus";
// Deploy-saga blind-spot specimens (civibus-7o7 + aug21 handoff §1). Every other
// fixture candidate name is mixed-case, so the raw-vs-formatted class
// (formatCandidatePublicName) passed vacuously until production served
// `OSSOFF, T. JONATHAN`. This identity-SAFE candidate stores the raw ALL-CAPS
// FEC filing string; every list/link/heading render must show the FORMATTED
// name, so a surface that bypasses the shared formatter goes red here instead
// of at the 8-minute production gate. Digit-free on purpose: the live identity
// predicate silently suppresses digit-bearing names, and this specimen must
// stay identity-safe.
export const SMOKE_ALLCAPS_CANDIDATE_ID = "cacacaca-caca-4aca-8aca-cacacacacaca";
export const SMOKE_ALLCAPS_CANDIDATE_RAW_NAME = "WHITFIELD, T. MARGARET";
export const SMOKE_ALLCAPS_CANDIDATE_FORMATTED_NAME = "Whitfield, T. Margaret";
// A committee whose FIRST linked candidate is identity-UNSAFE: the arrangement
// production could reorder into at any time (civibus-7o7). The deploy gate's
// linked-candidate journey shares its destination assertion with this fixture's
// twin spec, so the unsafe-first case is proven locally instead of discovered
// as a spurious deploy failure.
export const SMOKE_IDENTITY_JOURNEY_COMMITTEE_ID = "abababab-abab-4bab-8bab-abababababab";
export const SMOKE_IDENTITY_JOURNEY_COMMITTEE_NAME = "Identity Journey Committee";
// A >20-row org search set. Fixture search sets were all single-result, so the
// paged wording ("N results shown." vs "N results found.") was unreachable
// locally and failed the 2026-08-20 deploy gate against a healthy build.
export const SMOKE_PAGED_SEARCH_QUERY = "grove";
export const SMOKE_PAGED_SEARCH_TOTAL_ORG_COUNT = 21;
export const SMOKE_PAGED_SEARCH_FIRST_PAGE_STATUS = "20 results shown.";
export const SMOKE_PAGED_SEARCH_SECOND_PAGE_STATUS = "1 result shown.";
export const SMOKE_AL_CANDIDATE_TITLE = "Candidate Alabama | Candidate | Civibus";
export const SMOKE_AL_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";
export const SMOKE_GA_CANDIDATE_TITLE = "Candidate Georgia | Candidate | Civibus";
export const SMOKE_GA_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";

export const SMOKE_IE_COMMITTEE_A_ID = "dd111111-1111-4111-8111-111111111111";
export const SMOKE_IE_COMMITTEE_A_NAME = "Super PAC Alpha";
export const SMOKE_IE_TRANSACTION_DISSEMINATION_DATE = "2026-03-20";
export const SMOKE_CANDIDATE_SUPPORT_TOTAL = "$15,000.00";
export const SMOKE_CANDIDATE_OPPOSE_TOTAL = "$8,500.00";
export const SMOKE_CANDIDATE_OUTSIDE_SPENDING_EXPLANATION =
  "Outside spending is independent and not controlled by the candidate committee.";
export const SMOKE_CANDIDATE_OUTSIDE_SPENDING_COVERAGE_META =
  "2026 cycle, coverage through December 31, 2026. Unit: dollars";
export const SMOKE_CANDIDATE_OUTSIDE_SPENDING_CHART_SUMMARY =
  "Outside spending reports $15,000.00 in support spending and $8,500.00 in oppose spending for the 2026 cycle.";
export const SMOKE_CANDIDATE_OUTSIDE_SPENDING_EMPTY =
  "Outside-spending data is not yet available for this candidate. Coverage may be incomplete.";
export const SMOKE_COMMITTEE_IE_SUPPORT_TOTAL = "$1,500.00";
export const SMOKE_COMMITTEE_IE_OPPOSE_TOTAL = "$250.00";
export const SMOKE_COMMITTEE_IE_COUNT_LABEL = "3 expenditures";
export const SMOKE_COMMITTEE_IE_OUTLIER_NOTE =
  "1 reported independent expenditure was excluded from these totals as an outlier.";
export const SMOKE_COMMITTEE_IE_TARGET_NAME = SMOKE_CANDIDATE_NAME;
export const SMOKE_COMMITTEE_IE_SOURCE_NAME = "FEC Schedule E";
export const SMOKE_COMMITTEE_IE_SOURCE_RECORD_KEY = "committee-ie-source";
export const SMOKE_COMMITTEE_IE_SOURCE_URL = "https://www.fec.gov/data/independent-expenditures/";
export const SMOKE_COMMITTEE_OUTSIDE_SPENDING_EMPTY =
  "This committee reported no independent expenditures";
// The congress-directory scenario seeds a person of its own, so its name must
// differ from the browser-smoke seed specimen's. Both were SMOKE_PERSON_CANONICAL_NAME
// until test_support/browser_smoke_seed.py started writing a person with that
// name too: /congress then listed two members called "Jane Doe" and every
// name-based locator in congress.spec.ts hit a strict-mode violation. Distinct
// names are the fix, not a .first() on an ambiguous locator, which would have
// asserted against whichever row happened to sort first.
export const SMOKE_CONGRESS_PERSON_CANONICAL_NAME = "Dana Directory";
export const SMOKE_CONGRESS_PERSON_FIRST_NAME = "Dana";
export const SMOKE_CONGRESS_PERSON_LAST_NAME = "Directory";
export const SMOKE_CONGRESS_SEARCH_TERM = SMOKE_CONGRESS_PERSON_CANONICAL_NAME;
export const SMOKE_CONGRESS_MEMBER_CONTEXT = "House · NC · District 01 · DEM";
export const SMOKE_CONGRESS_PORTRAIT_URL =
  "data:image/gif;base64,R0lGODlhAQABAAAAACw=";
export const SMOKE_CONGRESS_PORTRAIT_ALT = `Portrait of ${SMOKE_CONGRESS_PERSON_CANONICAL_NAME}`;
export const SMOKE_CONGRESS_LEADER_PERSON_ID = SMOKE_PERSON_ID;
export const SMOKE_CONGRESS_LEADER_NAME = SMOKE_PERSON_CANONICAL_NAME;
export const SMOKE_CONGRESS_SECOND_PERSON_ID = "21111111-1111-4111-8111-111111111111";
export const SMOKE_CONGRESS_SECOND_NAME = "Alex Money Senator";
export const SMOKE_CONGRESS_NO_MONEY_PERSON_ID = "31111111-1111-4111-8111-111111111111";
export const SMOKE_CONGRESS_NO_MONEY_NAME = "Maria No Money Delegate";
export const SMOKE_CONGRESS_LEADER_TOTAL_RAISED = "$300.00";
export const SMOKE_CONGRESS_LEADER_TOTAL_RAISED_COMPACT = "$300";
export const SMOKE_CONGRESS_LEADER_OUTSIDE_SUPPORT = "$90.00";
export const SMOKE_CONGRESS_LEADER_OUTSIDE_AGAINST = "$30.00";
export const SMOKE_CONGRESS_LEADER_CASH_ON_HAND = "$60.00";
export const SMOKE_CONGRESS_SECOND_TOTAL_RAISED = "$100.00";
export const SMOKE_CONGRESS_SECOND_OUTSIDE_SUPPORT = "$20.00";
export const SMOKE_CONGRESS_SECOND_OUTSIDE_AGAINST = "$80.00";
export const SMOKE_CONGRESS_SECOND_CASH_ON_HAND = "$0.00";
export const SMOKE_CONGRESS_LEADER_SOURCE_HREF = "https://www.fec.gov/data/candidate/H6NC01001/";
export const SMOKE_CONGRESS_SECOND_SOURCE_HREF = "https://www.fec.gov/data/candidate/S6GA00001/";
// Live-seed leaderboard expectations (civibus-8lu). The values are owned by
// test_support/browser_smoke_seed.py: Jane Doe's candidate row (H6NC14001)
// and Alex Money Senator's (H6NC02001) official totals plus the four Schedule
// E rows written against them. Same journey, same members, same ordering as
// the fixture lane — only the dollars and source hrefs are seed-owned.
export const SMOKE_CONGRESS_LIVE_LEADER_TOTAL_RAISED = "$250.00";
export const SMOKE_CONGRESS_LIVE_LEADER_OUTSIDE_SUPPORT = "$90.00";
export const SMOKE_CONGRESS_LIVE_LEADER_OUTSIDE_AGAINST = "$30.00";
export const SMOKE_CONGRESS_LIVE_LEADER_CASH_ON_HAND = "$125.00";
export const SMOKE_CONGRESS_LIVE_LEADER_SOURCE_HREF =
  "https://example.org/browser-smoke/indiana-campaign-finance/record";
export const SMOKE_CONGRESS_LIVE_SECOND_TOTAL_RAISED = "$100.00";
export const SMOKE_CONGRESS_LIVE_SECOND_OUTSIDE_SUPPORT = "$20.00";
export const SMOKE_CONGRESS_LIVE_SECOND_OUTSIDE_AGAINST = "$80.00";
export const SMOKE_CONGRESS_LIVE_SECOND_CASH_ON_HAND = "$0.00";
export const SMOKE_CONGRESS_LIVE_SECOND_SOURCE_HREF =
  "https://example.org/browser-smoke/alex-money/record";
// The live seed now writes TWO candidates and TWO committees (civibus-8lu),
// so the browse lists' first-page labels differ from the single-row fixture
// lists. primary_nav_nonempty.spec.ts picks per mode.
export const SMOKE_CANDIDATES_FIRST_PAGE_LABEL_LIVE = "Showing 1–2";
export const SMOKE_COMMITTEES_FIRST_PAGE_LABEL_LIVE = "Showing 1–2";
export const SMOKE_CONGRESS_PERSON_ID = "90000000-0000-4000-8000-000000000411";
export const SMOKE_CONGRESS_CANDIDATE_ID = "90000000-0000-4000-8000-000000000412";
export const SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID = "90000000-0000-4000-8000-000000000413";
export const SMOKE_CONGRESS_IE_COMMITTEE_ID = "90000000-0000-4000-8000-000000000414";
export const SMOKE_CONGRESS_FILING_ID = "90000000-0000-4000-8000-000000000415";
export const SMOKE_CHART_LIVE_PERSON_ID = "94000000-0000-4000-8000-000000000411";
export const SMOKE_FINANCE_LIVE_PERSON_ID = "95000000-0000-4000-8000-000000000411";
// Live person-chart known-answer inputs. The charts-scenario 2026 committee summary
// seeds these so the receipt-source composition reconciles: individual + PAC sum to the
// total, and the total equals the candidate's official total_raised (the share
// denominator), yielding an exact 50/50 split. Kept here so the seed builder and the
// live row expectations read the same literals.
export const SMOKE_CHART_LIVE_RECEIPT_TOTAL_DOLLARS = "250.00";
export const SMOKE_CHART_LIVE_RECEIPT_INDIVIDUAL_DOLLARS = "125.00";
export const SMOKE_CHART_LIVE_RECEIPT_PAC_DOLLARS = "125.00";
export const SMOKE_CHART_LIVE_SUMMARY_COVERAGE_END = "2026-12-31";
export const SMOKE_CHART_LIVE_ALPHA_SUPPORT_TOTAL = "$10,000.00";
export const SMOKE_CHART_LIVE_ALPHA_OPPOSE_TOTAL = "$8,500.00";
export const SMOKE_CHART_LIVE_BETA_SUPPORT_TOTAL = "$5,000.00";
export const SMOKE_COMPARE_UNAVAILABLE_VALUE = "No reported/loaded money.";
export const SMOKE_FINANCE_LIVE_IE_COMMITTEE_B_NAME = "Civibus Future PAC";
export const SMOKE_COMPARE_LIVE_INPUTS = [
  {
    personId: "91000000-0000-4000-8000-000000000411",
    candidateId: "91000000-0000-4000-8000-000000000412",
    committeeId: "91000000-0000-4000-8000-000000000413",
    linkId: "91000000-0000-4000-8000-000000000408",
    fecCandidateId: "H0NC01991",
    fecCommitteeId: "C91000001",
    name: "Casey Exact Representative",
    totalRaised: "250.00",
    totalSpent: "80.00",
    cashOnHand: "170.00",
    candidateContrib: "50.00",
    candidateLoans: "25.00",
    candidateLoanRepay: "15.00",
    expectedSelfFundedShare: "24.0%"
  },
  {
    personId: "92000000-0000-4000-8000-000000000411",
    candidateId: "92000000-0000-4000-8000-000000000412",
    committeeId: "92000000-0000-4000-8000-000000000413",
    linkId: "92000000-0000-4000-8000-000000000408",
    fecCandidateId: "S0NC01992",
    fecCommitteeId: "C92000001",
    name: "Riley Exact Senator",
    totalRaised: "100.00",
    totalSpent: "20.00",
    cashOnHand: null,
    candidateContrib: "10.00",
    candidateLoans: "5.00",
    candidateLoanRepay: "0.00",
    expectedSelfFundedShare: "15.0%"
  }
] as const;
export const SMOKE_COMPARE_LIVE_OFFICEHOLDERS = SMOKE_COMPARE_LIVE_INPUTS.map((input) => {
  return {
    id: input.personId,
    name: input.name,
    expectedTotals: {
      "total-raised": formatSmokeCurrency(input.totalRaised),
      "total-spent": formatSmokeCurrency(input.totalSpent),
      "cash-on-hand":
        input.cashOnHand === null
          ? SMOKE_COMPARE_UNAVAILABLE_VALUE
          : formatSmokeCurrency(input.cashOnHand),
      "ie-support": SMOKE_COMPARE_UNAVAILABLE_VALUE,
      "ie-oppose": SMOKE_COMPARE_UNAVAILABLE_VALUE,
      "small-dollar-share": SMOKE_COMPARE_UNAVAILABLE_VALUE,
      "self-funded-share": input.expectedSelfFundedShare
    }
  };
});
// Live-mode /search smoke uses a fully independent officeholder fixture
// (Zorktown Q. Testperson, U.S. House NC-02, DEM) plus a same-name committee.
// The seed shape mirrors buildCongressSmokeSeedSql() but every id, FEC key,
// data_source, and source_record is disjoint from the congress seed so the
// two live specs can run in parallel workers without primary-key collisions.
// Stage 3 context assertion pins `office_name · state · party` per
// docs/reference/screen_specs/search.md.
export const SMOKE_SEARCH_LIVE_PERSON_NAME = "Zorktown Q. Testperson";
export const SMOKE_SEARCH_LIVE_QUERY = SMOKE_SEARCH_LIVE_PERSON_NAME;
export const SMOKE_SEARCH_LIVE_CONTEXT_LINE = "U.S. Representative · NC-02 · Democrat";
export const SMOKE_CANDIDATE_EMPTY_L10_WARNING =
  "No transactions loaded for this candidate yet. Coverage may be incomplete.";
export const SMOKE_CANDIDATE_DEVIATION_L10_WARNING =
  "Civibus shows $250.00 raised, but the NC SBOE anchor reference is $1,000.00. Coverage may be incomplete.";
export const SMOKE_CANDIDATE_AL_FRESHNESS_WARNING =
  "Alabama campaign finance production data is currently a narrow committee-state slice; totals may be incomplete.";
export const SMOKE_CANDIDATE_GA_FRESHNESS_WARNING =
  "Georgia campaign finance production data is currently a narrow committee-state slice; totals may be incomplete.";
export const SMOKE_PHL_FRESHNESS_WARNING =
  "Philadelphia campaign finance bulk data has an observed ~27 day publication lag; this view may be weeks behind recent filings.";

export const SMOKE_PROPERTY_TITLE = "123 MAIN ST";
export const SMOKE_PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE =
  "Map data unavailable: this parcel response does not include coordinates or boundary geometry.";
export const SMOKE_PROPERTY_PAGE_TITLE = "123 MAIN ST | Property | Civibus";
export const SMOKE_PROPERTY_DESCRIPTION = "Property profile with 1 ownership record and 1 assessment.";
export const SMOKE_EMPTY_PROPERTY_TITLE = "999 EMPTY RD";
export const SMOKE_EMPTY_PROPERTY_PAGE_TITLE = "999 EMPTY RD | Property | Civibus";
export const SMOKE_EMPTY_PROPERTY_DESCRIPTION = "Property profile with 0 ownership records and 0 assessments.";

export const SMOKE_CONTEST_ID = process.env.SMOKE_CONTEST_ID ?? "ab111111-1111-4111-8111-111111111111";
export const SMOKE_CANDIDACY_ID = "ac111111-1111-4111-8111-111111111111";
export const SMOKE_OFFICEHOLDING_ID = "ad111111-1111-4111-8111-111111111111";

export const SMOKE_CONTEST_NAME = "2026 NC Senate General";
export const SMOKE_CONTEST_TITLE = "2026 NC Senate General | Contest | Civibus";
export const SMOKE_CONTEST_DESCRIPTION = "Contest profile with 1 candidacy.";
export const SMOKE_CANDIDACY_PERSON_NAME = "Jane Doe";
export const SMOKE_CANDIDACY_TITLE = "Jane Doe | Candidacy | Civibus";
export const SMOKE_CANDIDACY_DESCRIPTION = "Candidacy profile for Jane Doe.";
export const SMOKE_CONTEST_WINNER_NAME = SMOKE_CANDIDACY_PERSON_NAME;
export const SMOKE_CONTEST_FINANCE_LINK_NAME = "View candidate finance profile";

export const SMOKE_OFFICEHOLDING_PERSON_NAME = "Jane Doe";
export const SMOKE_OFFICEHOLDING_TITLE = "Jane Doe | Officeholding | Civibus";
export const SMOKE_OFFICEHOLDING_DESCRIPTION = "Officeholding profile for Jane Doe.";

export const SMOKE_OFFICE_NAME = "U.S. Senator, North Carolina";
export const SMOKE_OFFICE_TITLE = "U.S. Senator, North Carolina | Office | Civibus";
export const SMOKE_OFFICE_DESCRIPTION = "Office profile with 1 current officeholder.";
export const SMOKE_OFFICE_OFFICEHOLDER_NAME = "Jane Doe";
export const SMOKE_EMPTY_OFFICE_NAME = "State Auditor, North Carolina";
export const SMOKE_EMPTY_OFFICE_TITLE = "State Auditor, North Carolina | Office | Civibus";
export const SMOKE_EMPTY_OFFICE_DESCRIPTION = "Office profile with 0 current officeholders.";
export const SMOKE_OFFICE_INCOMPLETE_DATA_WARNING = "Current officeholder data is incomplete for this office.";
export const SMOKE_OFFICE_RECENT_CONTEST_NAME = SMOKE_CONTEST_NAME;

export const SMOKE_PROVENANCE_SOURCE_NAME = "FEC (campaign_finance/federal/fec)";
export const SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME =
  "Indiana Campaign Finance (campaign_finance/state/IN)";
export const SMOKE_CAMPAIGN_FINANCE_AL_PROVENANCE_SOURCE_NAME =
  "Alabama Campaign Finance (campaign_finance/state/AL)";
export const SMOKE_CAMPAIGN_FINANCE_GA_PROVENANCE_SOURCE_NAME =
  "Georgia Campaign Finance (campaign_finance/state/GA)";
export const SMOKE_PHL_PROVENANCE_SOURCE_NAME =
  "Philadelphia Campaign Finance (campaign_finance/municipality/PHL)";
// SMOKE_IN_FRESHNESS_WARNING constant retired 2026-04-26 after the IN
// re-verdict to weekly-or-better — the spec now asserts the literal
// string is absent from the page rather than importing a fixture named
// after a banner that no longer exists. See
// docs/reference/research/in_freshness_recheck_2026_04_26.md.
export const SMOKE_PROPERTY_PROVENANCE_SOURCE_NAME = "Durham County (property/us/nc/durham)";
export const SMOKE_PROVENANCE_LAST_PULLED = /^Last pulled: (?:today|\d+ days? ago) \(\d{4}-\d{2}-\d{2}\)$/;
export const SMOKE_PROVENANCE_SOURCE_KEY = "Source record ID: person-1";
export const SMOKE_PROPERTY_PROVENANCE_SOURCE_KEY = "Source record ID: parcel-1";
export const SMOKE_TRUST_ADVISORY = "Review source records before publication.";
export const SMOKE_TRUST_EMPTY_MESSAGE = "No source records are available for this detail yet.";
export const SMOKE_TRUST_LAST_PULLED_UNAVAILABLE = "Last pulled: unavailable";
export const SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING = "Campaign finance";
export const SMOKE_PERSON_FUNDRAISING_DETAIL_HEADING = "Fundraising detail";
export const SMOKE_PERSON_DONATIONS_OVER_TIME_HEADING = "Donations over time";
export const SMOKE_PERSON_DONATION_COUNT_BY_SIZE_HEADING = "Donation count by size bucket";
export const SMOKE_PERSON_DOLLARS_BY_SIZE_HEADING = "Dollars by size bucket";
export const SMOKE_PERSON_FUNDRAISING_GEOGRAPHY_HEADING = "Fundraising geography";
export const SMOKE_PERSON_MONEY_AT_GLANCE_HEADING = "Money at a glance";
export const SMOKE_PERSON_SELECTED_CYCLE = "2026";
export const SMOKE_PERSON_MONEY_COVERAGE = `2026-01-01 to ${SMOKE_CANDIDATE_COVERAGE_THROUGH}`;
export const SMOKE_PERSON_MONEY_SOURCE_LABEL = "Official FEC candidate summary";
export const SMOKE_PERSON_MONEY_RECEIPTS = SMOKE_CANDIDATE_TOTAL_RAISED;
export const SMOKE_PERSON_MONEY_DISBURSEMENTS = SMOKE_CANDIDATE_TOTAL_SPENT;
export const SMOKE_PERSON_MONEY_CASH_ON_HAND = SMOKE_CANDIDATE_CASH_ON_HAND;
export const SMOKE_PERSON_MONEY_DEBTS_OWED = "$0.00";
export const SMOKE_PERSON_RECEIPT_COMPOSITION_SUMMARY =
  "Receipt components disclose $250.00 in total receipts for the 2026 cycle.";
export const SMOKE_PERSON_SUMMARY_CHART_COVERAGE_META =
  "2026 cycle, coverage through December 31, 2026. Unit: dollars";
export const SMOKE_PERSON_CONTRIBUTION_CHART_COVERAGE_META =
  "2026 cycle, coverage through June 30, 2026. Unit: dollars";
export const SMOKE_PERSON_MONTHLY_CONTRIBUTIONS_SUMMARY =
  "Itemized individual contributions total $350.00 in the 2026 cycle.";
export const SMOKE_PERSON_DOLLARS_BY_SIZE_SUMMARY =
  "Itemized contribution-size buckets discloses $350.00 across 2 reported transactions in the 2026 cycle.";
export const SMOKE_PERSON_REPORTED_TRANSACTIONS_BY_SIZE_SUMMARY =
  "Itemized contribution-size buckets discloses $350.00 across 2 reported transactions in the 2026 cycle.";
export const SMOKE_PERSON_GEOGRAPHY_SUMMARY =
  "Unknown is included in the visible geography denominator. Unknown is $0.00 with 0 reported transactions; visible denominator is $350.00.";
export const SMOKE_PERSON_OUTSIDE_SPENDING_SUMMARY =
  "Outside spending reports $15,000.00 in support spending and $8,500.00 in oppose spending for the 2026 cycle.";
const SMOKE_MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December"
] as const;
const SMOKE_ZERO_MONTHLY_CONTRIBUTION = { dollars: "$0.00", transactions: "0" };
const SMOKE_MONTHLY_CONTRIBUTIONS_BY_MONTH: Record<
  string,
  { dollars: string; transactions: string }
> = {
  "2026-01": { dollars: "$125.00", transactions: "1" },
  "2026-02": { dollars: "$225.00", transactions: "1" }
};
function buildSmokeMonthlyContributionRows(startYear: number, monthCount: number) {
  return Array.from({ length: monthCount }, (_, index) => {
    const year = startYear + Math.floor(index / SMOKE_MONTH_NAMES.length);
    const monthIndex = index % SMOKE_MONTH_NAMES.length;
    const monthKey = `${year}-${String(monthIndex + 1).padStart(2, "0")}`;
    const contribution =
      SMOKE_MONTHLY_CONTRIBUTIONS_BY_MONTH[monthKey] ?? SMOKE_ZERO_MONTHLY_CONTRIBUTION;

    return {
      label: `${SMOKE_MONTH_NAMES[monthIndex]} ${year}`,
      values: [
        `Dollars: ${contribution.dollars}`,
        `Transactions: ${contribution.transactions}`,
        "Coverage: Covered"
      ]
    };
  });
}
export const SMOKE_CHART_DATA_ACCESS_MONTHLY_ROWS = buildSmokeMonthlyContributionRows(2022, 54);
export const SMOKE_CHART_LIVE_DATA_ACCESS_MONTHLY_ROWS = buildSmokeMonthlyContributionRows(
  2025,
  24
);
export const SMOKE_CHART_DATA_ACCESS_ROWS = {
  receiptComposition: [
    {
      label: "Gross individual contributions",
      values: ["Dollars: $125.00", "Share: 50%", "Denominator: $250.00"]
    },
    {
      label: "PAC/other committee contributions",
      values: ["Dollars: $125.00", "Share: 50%", "Denominator: $250.00"]
    }
  ],
  monthlyContributions: SMOKE_CHART_DATA_ACCESS_MONTHLY_ROWS,
  sizeBuckets: [
    {
      label: "$200 and under",
      values: ["Dollars: $125.00", "Transactions: 1"]
    },
    {
      label: "$200.01-$499.99",
      values: ["Dollars: $225.00", "Transactions: 1"]
    },
    {
      label: "$500-$999.99",
      values: ["Dollars: $0.00", "Transactions: 0"]
    },
    {
      label: "$1,000-$1,999.99",
      values: ["Dollars: $0.00", "Transactions: 0"]
    },
    {
      label: "$2,000 and over",
      values: ["Dollars: $0.00", "Transactions: 0"]
    }
  ],
  geographyShare: [
    {
      label: "In district",
      values: ["Dollars: $125.00", "Transactions: 1", "Denominator: $350.00"]
    },
    {
      label: "Out of district",
      values: ["Dollars: $225.00", "Transactions: 1", "Denominator: $350.00"]
    },
    {
      label: "Unknown",
      values: ["Dollars: $0.00", "Transactions: 0", "Denominator: $350.00"]
    }
  ],
  outsideSpending: [
    {
      label: "Support spending",
      values: ["Dollars: $15,000.00", "Transactions: 12"]
    },
    {
      label: "Oppose spending",
      values: ["Dollars: $8,500.00", "Transactions: 5"]
    },
    {
      label: `Top spender: ${SMOKE_IE_COMMITTEE_A_NAME}`,
      // The top-spender row also discloses the spender's stance; a support
      // spender renders "Support spending" (OutsideSpendingChart.svelte).
      values: ["Dollars: $10,000.00", "Transactions: 8", "Stance: Support spending"]
    }
  ]
} as const;
export const SMOKE_CHART_LIVE_DATA_ACCESS_ROWS = {
  ...SMOKE_CHART_DATA_ACCESS_ROWS,
  monthlyContributions: SMOKE_CHART_LIVE_DATA_ACCESS_MONTHLY_ROWS,
  geographyShare: [
    {
      label: "In district",
      values: ["Dollars: $125.00", "Transactions: 1", "Denominator: $350.00"]
    },
    {
      label: "Elsewhere in state",
      values: ["Dollars: $225.00", "Transactions: 1", "Denominator: $350.00"]
    },
    {
      label: "Unknown",
      values: ["Dollars: $0.00", "Transactions: 0", "Denominator: $350.00"]
    }
  ],
  receiptComposition: [
    {
      label: "Individual contributions",
      values: ["Dollars: $125.00", "Share: 50%", "Denominator: $250.00"]
    },
    {
      label: "PAC/other committee contributions",
      values: ["Dollars: $125.00", "Share: 50%", "Denominator: $250.00"]
    },
    {
      label: "Party committee contributions",
      values: ["Dollars: $0.00", "Share: 0%", "Denominator: $250.00"]
    },
    {
      label: "Candidate funding",
      values: ["Dollars: $0.00", "Share: 0%", "Denominator: $250.00"]
    },
    {
      label: "Transfers from other authorized committees",
      values: ["Dollars: $0.00", "Share: 0%", "Denominator: $250.00"]
    },
    {
      label: "Other receipts",
      values: ["Dollars: $0.00", "Share: 0%", "Denominator: $250.00"]
    }
  ],
  outsideSpending: [
    {
      label: "Support spending",
      values: ["Dollars: $15,000.00", "Transactions: 12"]
    },
    {
      label: "Oppose spending",
      values: ["Dollars: $8,500.00", "Transactions: 5"]
    },
    {
      label: `Top spender: ${SMOKE_IE_COMMITTEE_A_NAME}`,
      values: [
        `Dollars: ${SMOKE_CHART_LIVE_ALPHA_SUPPORT_TOTAL}`,
        "Transactions: 8",
        "Stance: Support spending"
      ]
    },
    {
      label: `Top spender: ${SMOKE_IE_COMMITTEE_A_NAME}`,
      values: [
        `Dollars: ${SMOKE_CHART_LIVE_ALPHA_OPPOSE_TOTAL}`,
        "Transactions: 5",
        "Stance: Oppose spending"
      ]
    },
    {
      label: `Top spender: ${SMOKE_FINANCE_LIVE_IE_COMMITTEE_B_NAME}`,
      values: [
        `Dollars: ${SMOKE_CHART_LIVE_BETA_SUPPORT_TOTAL}`,
        "Transactions: 4",
        "Stance: Support spending"
      ]
    }
  ]
} as const;
export const SMOKE_PERSON_UNITEMIZED_DOLLARS = "150.00";
export const SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS = "125.00";
export const SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS = "225.00";
export const SMOKE_PERSON_ITEMIZED_DOLLARS = "350.00";
export const SMOKE_PERSON_TOTAL_CONTRIBUTION_DOLLARS = "500.00";
export const SMOKE_PERSON_CASH_ON_HAND_DOLLARS = "420.00";
export const SMOKE_PERSON_SMALL_DOLLAR_DOLLARS = "350.00";
export const SMOKE_PERSON_SMALL_DOLLAR_SHARE = "0.6087";
export const SMOKE_PERSON_SMALL_DOLLAR_HEADLINE = `${Math.round(Number(SMOKE_PERSON_SMALL_DOLLAR_SHARE) * 100)}%`;
export const SMOKE_PERSON_CYCLE_TOTAL_LABEL = "2026 cycle";
export const SMOKE_PERSON_CYCLE_TOTAL = "$500.00";
export const SMOKE_PERSON_CAREER_TOTAL_LABEL = "Recent history total (2022-2026)";
export const SMOKE_PERSON_CAREER_TOTAL = "$575.00";
export const SMOKE_PERSON_PRIOR_UNITEMIZED_DOLLARS = "75.00";
export const SMOKE_PERSON_TOP_DONORS_HEADING = "Top reported contributor names";
export const SMOKE_PERSON_TOP_DONOR_ONE_NAME = "Smoke Donor Two";
export const SMOKE_PERSON_TOP_DONOR_TWO_NAME = "Smoke Donor One";
export const SMOKE_PERSON_TOP_DONOR_ONE_TOTAL = "$225.00";
export const SMOKE_PERSON_TOP_DONOR_TWO_TOTAL = "$125.00";
export const SMOKE_PERSON_TOP_EMPLOYERS_HEADING = "Top reported employer names";
export const SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME = "GOOGLE";
export const SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME = "ACME CORP";
export const SMOKE_PERSON_TOP_EMPLOYER_THREE_NAME = "Unclassified / not provided";
export const SMOKE_PERSON_TOP_EMPLOYER_ONE_TOTAL = "$600.00";
export const SMOKE_PERSON_TOP_EMPLOYER_TWO_TOTAL = "$150.00";
export const SMOKE_PERSON_TOP_EMPLOYER_THREE_TOTAL = "$25.00";
export const SMOKE_PERSON_TOP_EMPLOYER_DISCLAIMER =
  "Top employers aggregate raw employer names from itemized individual contributions only.";
export const SMOKE_PERSON_TOP_EMPLOYER_METHODOLOGY =
  "The raw ranking remains employer-name data; see Methodology for source-linking and evidence limitations.";
export const SMOKE_PERSON_DISTRICT_SHARE_HEADLINE = "36% in district";
export const SMOKE_PERSON_DISTRICT_SHARE_SUMMARY =
  "$125.00 in district and $225.00 out of district.";
export const SMOKE_PERSON_APPROXIMATE_GEOGRAPHY_NOTE =
  "District geography uses a Census 119th-Congress / 2020-ZCTA approximation.";
export const SMOKE_PERSON_TOP_SPENDERS_HEADING = "Top spenders";
export const SMOKE_PERSON_TOP_SPENDER_NAME = SMOKE_IE_COMMITTEE_A_NAME;
export const SMOKE_PERSON_TOP_SPENDER_TOTAL = SMOKE_CHART_LIVE_ALPHA_SUPPORT_TOTAL;
export const SMOKE_PERSON_TOP_DONOR_ROWS = [
  {
    name: SMOKE_PERSON_TOP_DONOR_ONE_NAME,
    total: SMOKE_PERSON_TOP_DONOR_ONE_TOTAL,
    transactions: "1 transaction"
  },
  {
    name: SMOKE_PERSON_TOP_DONOR_TWO_NAME,
    total: SMOKE_PERSON_TOP_DONOR_TWO_TOTAL,
    transactions: "1 transaction"
  }
] as const;
export const SMOKE_PERSON_TOP_EMPLOYER_ROWS = [
  {
    name: SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
    total: SMOKE_PERSON_TOP_EMPLOYER_ONE_TOTAL,
    transactions: "3 transactions"
  },
  {
    name: SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME,
    total: SMOKE_PERSON_TOP_EMPLOYER_TWO_TOTAL,
    transactions: "1 transaction"
  },
  {
    name: SMOKE_PERSON_TOP_EMPLOYER_THREE_NAME,
    total: SMOKE_PERSON_TOP_EMPLOYER_THREE_TOTAL,
    transactions: "1 transaction"
  }
] as const;
export const SMOKE_PERSON_TOP_SPENDER_ROWS = [
  {
    name: SMOKE_PERSON_TOP_SPENDER_NAME,
    stance: "Support",
    total: SMOKE_PERSON_TOP_SPENDER_TOTAL,
    transactions: "8 expenditures"
  }
] as const;
export const SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS = [
  { name: "Smoke Finance Donor One", total: "$225.00", transactions: "1 transaction" },
  { name: "Smoke Finance Donor Two", total: "$200.00", transactions: "1 transaction" },
  { name: "Smoke Finance Donor Three", total: "$175.00", transactions: "1 transaction" },
  { name: "Smoke Finance Donor Four", total: "$150.00", transactions: "1 transaction" },
  { name: "Smoke Finance Donor Five", total: "$25.00", transactions: "1 transaction" }
] as const;
export const SMOKE_FINANCE_LIVE_TOP_EMPLOYER_ROWS = [
  {
    name: SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
    total: SMOKE_PERSON_TOP_EMPLOYER_ONE_TOTAL,
    transactions: "3 transactions"
  },
  {
    name: SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME,
    total: SMOKE_PERSON_TOP_EMPLOYER_TWO_TOTAL,
    transactions: "1 transaction"
  },
  {
    name: SMOKE_PERSON_TOP_EMPLOYER_THREE_NAME,
    total: SMOKE_PERSON_TOP_EMPLOYER_THREE_TOTAL,
    transactions: "1 transaction"
  }
] as const;
export const SMOKE_FINANCE_LIVE_TOP_SPENDER_ROWS = [
  {
    name: SMOKE_PERSON_TOP_SPENDER_NAME,
    stance: "Support",
    total: SMOKE_PERSON_TOP_SPENDER_TOTAL,
    transactions: "8 expenditures"
  },
  {
    name: SMOKE_PERSON_TOP_SPENDER_NAME,
    stance: "Oppose",
    total: SMOKE_CHART_LIVE_ALPHA_OPPOSE_TOTAL,
    transactions: "5 expenditures"
  },
  {
    name: SMOKE_FINANCE_LIVE_IE_COMMITTEE_B_NAME,
    stance: "Support",
    total: SMOKE_CHART_LIVE_BETA_SUPPORT_TOTAL,
    transactions: "4 expenditures"
  }
] as const;
export const SMOKE_PERSON_UNITEMIZED_BUCKET_LABEL = "Unitemized (<$200)";
export const SMOKE_PERSON_UNITEMIZED_EXCLUSION_NOTE =
  "Unitemized contributions are excluded from count and geography charts.";
export const SMOKE_PERSON_LINKED_COMMITTEES_HEADING = "Linked committees";
export const SMOKE_PERSON_DONORS_AND_VENDORS_HEADING = "Donors and vendors";
export const SMOKE_PERSON_OUTSIDE_SPENDING_HEADING = "Outside spending";
export const SMOKE_COMMITTEE_EMPTY_STATE = "No recent committee transactions found.";
export const SMOKE_PROPERTY_EMPTY_OWNERSHIP_STATE = "No ownership history is available yet. Check back after the next county refresh.";
export const SMOKE_PROPERTY_EMPTY_ASSESSMENT_STATE = "No assessment history is available yet. Check back after the next county refresh.";
export const SMOKE_OFFICEHOLDER_EMPTY_STATE = "No current officeholders are linked yet. Check back after the next records refresh.";

// SQL builders + live-mode seed wrappers moved to ./smoke-seed-sql so this file
// stays under the 800-line hard limit and single-owner rule applies:
// smoke-seed-sql.ts owns every SQL string, and fixtures.ts owns every constant.
// @ts-expect-error Smoke fixtures run under Node ESM and import the TS module directly.
export { buildCongressSmokeCleanupSql, buildCongressSmokeSeedSql, seedLiveCongressDirectorySmoke, seedLiveSearchOfficeholderSmoke } from "./smoke-seed-sql.ts";
// @ts-expect-error Smoke fixtures run under Node ESM and import the TS module directly.
export { seedLiveStage6CommitteeSmoke } from "./stage6_committee_seed_sql.ts";
// Stage 6 committee truthfulness fixtures.
//
// Local live mode: discovers a real committee named MIKE JOHNSON FOR LOUISIANA
// through the live campaign-finance API and returns its detail route + a set
// of stable assertions that would have failed as a false $0 before this stage
// (positive official total_raised even when itemized_transaction_count is 0).
//
// Production mode: production is read-only — the seed helpers below are for
// local live-mode only. Production smoke discovers the committee to visit by
// clicking through /congress -> member page -> principal committee link, so
// the test never hard-codes an ephemeral UUID or slug.

export const SMOKE_STAGE6_COMMITTEE_NAME = "MIKE JOHNSON FOR LOUISIANA";
// Seeded committee is a synthetic FEC-summary-official record used only for
// live smoke: its official total_raised is positive while its itemized
// transaction count is zero, reproducing the false-$0 pattern this stage
// fixes.
export const SMOKE_STAGE6_COMMITTEE_ID = "50000000-0000-4000-8000-000000000001";
export const SMOKE_STAGE6_LINKED_CANDIDATE_ID = "50000000-0000-4000-8000-000000000002";
export const SMOKE_STAGE6_LINKED_CANDIDATE_NAME = "MIKE JOHNSON";
export const SMOKE_STAGE6_SUMMARY_SOURCE_LABEL =
  COMMITTEE_SUMMARY_SOURCE_LABELS.fec_committee_summary;
export const SMOKE_STAGE6_ITEMIZED_COVERAGE_NOTE = buildCommitteeItemizedCoverageNote({
  itemized_transaction_count: 0,
  summary_source: "fec_committee_summary"
});
export const SMOKE_STAGE6_COMMITTEE_TOTAL_RAISED_LITERAL = "$1,250,000.00";
// The past cycle the Stage 6 seed writes a committee_summary row for, so the
// journey covers a real historical record and not only the current cycle. It is
// NOT what the spec asserts under "Per-cycle history" — the page renders the
// summaries for the cycle the API selected, which getSeededStage6CommitteeRoute
// reads from the response.
export const SMOKE_STAGE6_COMMITTEE_CYCLE_LABEL = "2024";

export const SMOKE_STAGE6_FEC_COMMITTEE_ID = "C90099901";
export const SMOKE_STAGE6_FEC_CANDIDATE_ID = "H0LA04901";
export const SMOKE_STAGE6_DATA_SOURCE_ID = "50000000-0000-4000-8000-000000000010";
export const SMOKE_STAGE6_SOURCE_RECORD_ID = "50000000-0000-4000-8000-000000000011";
export const SMOKE_STAGE6_COMMITTEE_SUMMARY_ID = "50000000-0000-4000-8000-000000000012";
// A second summary row, written at the cycle the committee page selects by
// default. api/queries/campaign_finance.py resolves that as
// max(SUPPORTED_COMMITTEE_SUMMARY_CYCLES), which moved to 2026 while this
// fixture still only carried a 2024 summary — so the default view fell back to
// "derived from itemized transactions" and reported $0.00, and the journey that
// exists to prove a positive official total is never rendered as a false $0
// failed on its own fixture. The cycle is discovered from the API at seed time
// rather than pinned here, so the next cycle rollover cannot re-stale it.
export const SMOKE_STAGE6_CURRENT_CYCLE_SUMMARY_ID = "50000000-0000-4000-8000-000000000014";
export const SMOKE_STAGE6_LINK_ID = "50000000-0000-4000-8000-000000000013";
const SMOKE_STAGE6_COMMITTEE_SLUG = "mike-johnson-for-louisiana";

export const SMOKE_LIVE_API_BASE_URL =
  process.env.SMOKE_LIVE_API_BASE_URL ?? "http://127.0.0.1:8000";

export type LiveCommitteeRouteDiscovery = {
  committeePath: string;
  expectedSummarySourceLabel: string;
  expectedItemizedCoverageNote: string;
  expectedLinkedCandidateName: string;
  expectedCycleLabel: string;
  expectedTotalRaisedText: string;
  expectedOutsideSpendingEmptyText: string | null;
  expectedOutsideSpendingTargetName: string | null;
};

/**
 * Assertions for the seeded Stage 6 committee.
 *
 * Everything the seed writes stays a pinned literal - the whole point is that a
 * positive official total renders instead of a false $0 while itemized
 * transactions are zero. The cycle label is the one value the seed does not own:
 * the committee page renders `cycle_summaries` for the cycle the API selected,
 * and that selection is max(SUPPORTED_COMMITTEE_SUMMARY_CYCLES) in
 * api/queries/campaign_finance.py, which moves. Pinning it as "2024" is what
 * broke this journey when the supported tuple grew a 2026 entry. Deriving it
 * from the same response the live-data branch of this discovery already derives
 * from keeps one pattern rather than two.
 */
export function getSeededStage6CommitteeRoute(
  summary: LiveCommitteeSummaryResponse
): LiveCommitteeRouteDiscovery {
  const cycle = summary.cycle_summaries?.[0]?.cycle;
  if (typeof cycle !== "number") {
    throw new Error(
      "Seeded Stage 6 committee: summary carries no cycle_summaries row, so the seeded official totals are not being served"
    );
  }
  return {
    committeePath: `/committee/${SMOKE_STAGE6_COMMITTEE_ID}`,
    expectedSummarySourceLabel: SMOKE_STAGE6_SUMMARY_SOURCE_LABEL,
    expectedItemizedCoverageNote: SMOKE_STAGE6_ITEMIZED_COVERAGE_NOTE,
    expectedLinkedCandidateName: SMOKE_STAGE6_LINKED_CANDIDATE_NAME,
    expectedCycleLabel: String(cycle),
    expectedTotalRaisedText: SMOKE_STAGE6_COMMITTEE_TOTAL_RAISED_LITERAL,
    expectedOutsideSpendingEmptyText: SMOKE_COMMITTEE_OUTSIDE_SPENDING_EMPTY,
    expectedOutsideSpendingTargetName: null
  };
}

type SmokeApiJsonResponse = {
  ok: () => boolean;
  status: () => number;
  json: () => Promise<unknown>;
};

type SmokePageApiClient = {
  request: {
    get: (url: string) => Promise<SmokeApiJsonResponse>;
  };
};

type LiveSearchCommitteeResult = {
  id?: string;
  name?: string;
  slug?: string;
  slug_is_unique?: boolean;
};

type LiveSearchCommitteeResponse = {
  items?: Array<{
    entity_id?: string;
    name?: string;
  }>;
  has_next?: boolean;
};

type LiveCommitteeDetailResponse = {
  linked_candidates?: Array<{ name?: string }>;
};

type LiveCommitteeSummaryResponse = {
  total_raised?: string;
  itemized_transaction_count?: number;
  cycle_summaries?: Array<{ cycle?: number }>;
  summary_source?: "fec_committee_summary" | "derived";
};

type LiveCommitteeIndependentExpenditureResponse = {
  ie_transaction_count?: number;
  targets?: Array<{ candidate_name?: string }>;
};

function resolveDiscoveredCommitteeRouteId(match: LiveSearchCommitteeResult): string {
  return match.slug_is_unique === true && typeof match.slug === "string" ? match.slug : String(match.id);
}

function formatSmokeCurrency(value: string): string {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    throw new Error(`Live committee discovery: invalid money value "${value}"`);
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD"
  }).format(parsed);
}


/**
 */
async function fetchLiveCommitteeDiscoveryRecord(
  page: SmokePageApiClient,
  committeeId: string
): Promise<{
  detail: LiveCommitteeDetailResponse;
  summary: LiveCommitteeSummaryResponse;
  independentExpendituresMade: LiveCommitteeIndependentExpenditureResponse;
}> {
  const [detailResponse, summaryResponse, independentExpendituresMadeResponse] = await Promise.all([
    page.request.get(`${SMOKE_LIVE_API_BASE_URL}/v1/committees/${committeeId}`),
    page.request.get(`${SMOKE_LIVE_API_BASE_URL}/v1/committees/${committeeId}/summary`),
    page.request.get(
      `${SMOKE_LIVE_API_BASE_URL}/v1/committees/${committeeId}/independent-expenditures-made`
    )
  ]);

  if (!detailResponse.ok()) {
    throw new Error(
      `Live committee discovery failed: /v1/committees/${committeeId} returned ${detailResponse.status()}`
    );
  }
  if (!summaryResponse.ok()) {
    throw new Error(
      `Live committee discovery failed: /v1/committees/${committeeId}/summary returned ${summaryResponse.status()}`
    );
  }
  if (!independentExpendituresMadeResponse.ok()) {
    throw new Error(
      `Live committee discovery failed: /v1/committees/${committeeId}/independent-expenditures-made returned ${independentExpendituresMadeResponse.status()}`
    );
  }

  return {
    detail: (await detailResponse.json()) as LiveCommitteeDetailResponse,
    summary: (await summaryResponse.json()) as LiveCommitteeSummaryResponse,
    independentExpendituresMade:
      (await independentExpendituresMadeResponse.json()) as LiveCommitteeIndependentExpenditureResponse
  };
}

/**
 */
function buildDiscoveredLiveCommitteeAssertions(
  routeId: string,
  record: {
    detail: LiveCommitteeDetailResponse;
    summary: LiveCommitteeSummaryResponse;
    independentExpendituresMade: LiveCommitteeIndependentExpenditureResponse;
  }
): LiveCommitteeRouteDiscovery {
  const totalRaised = record.summary.total_raised;
  const itemizedTransactionCount = record.summary.itemized_transaction_count;
  const summarySource = record.summary.summary_source;
  const cycle = record.summary.cycle_summaries?.[0]?.cycle;
  const linkedCandidateName = record.detail.linked_candidates?.[0]?.name;
  const ieTransactionCount = record.independentExpendituresMade.ie_transaction_count;
  const firstIeTargetName = record.independentExpendituresMade.targets?.[0]?.candidate_name;

  if (typeof totalRaised !== "string") {
    throw new Error("Live committee discovery: summary total_raised is missing");
  }
  if (typeof itemizedTransactionCount !== "number") {
    throw new Error("Live committee discovery: summary itemized_transaction_count is missing");
  }
  if (summarySource !== "fec_committee_summary" && summarySource !== "derived") {
    throw new Error("Live committee discovery: summary_source is missing");
  }
  if (typeof cycle !== "number") {
    throw new Error("Live committee discovery: summary cycle_summaries is empty");
  }
  if (typeof linkedCandidateName !== "string" || linkedCandidateName.trim() === "") {
    throw new Error("Live committee discovery: linked candidate name is missing");
  }
  if (typeof ieTransactionCount !== "number") {
    throw new Error("Live committee discovery: independent-expenditures-made count is missing");
  }
  if (ieTransactionCount > 0 && (typeof firstIeTargetName !== "string" || firstIeTargetName.trim() === "")) {
    throw new Error("Live committee discovery: independent-expenditures-made target name is missing");
  }

  return {
    committeePath: `/committee/${routeId}`,
    expectedSummarySourceLabel: COMMITTEE_SUMMARY_SOURCE_LABELS[summarySource],
    expectedItemizedCoverageNote: buildCommitteeItemizedCoverageNote({
      itemized_transaction_count: itemizedTransactionCount,
      summary_source: summarySource
    }),
    expectedLinkedCandidateName: linkedCandidateName,
    expectedCycleLabel: String(cycle),
    expectedTotalRaisedText: formatSmokeCurrency(totalRaised),
    expectedOutsideSpendingEmptyText:
      ieTransactionCount === 0 ? SMOKE_COMMITTEE_OUTSIDE_SPENDING_EMPTY : null,
    expectedOutsideSpendingTargetName: ieTransactionCount > 0 ? firstIeTargetName ?? null : null
  };
}

/**
 * Discovers the Louisiana committee route in local live mode.
 *
 * Live mode covers two paths: (1) a real DB row for MIKE JOHNSON FOR LOUISIANA
 * whose official FEC totals are already loaded, or (2) the seeded Stage 6
 * committee inserted by seedLiveStage6CommitteeSmoke() when the real row is
 * not present. Either way, the returned assertions reflect the false-$0 gap
 * this stage closes (positive official total with zero itemized transactions).
 */
export async function discoverLiveLouisianaCommitteeRoute(page: {
  request: {
    get: (
      url: string
    ) => Promise<{ ok: () => boolean; status: () => number; json: () => Promise<unknown> }>;
  };
}): Promise<LiveCommitteeRouteDiscovery> {
  const seededRouteResponse = await page.request.get(
    `${SMOKE_LIVE_API_BASE_URL}/v1/committees/by-slug/${SMOKE_STAGE6_COMMITTEE_SLUG}`
  );
  if (seededRouteResponse.ok()) {
    const slugMatches = (await seededRouteResponse.json()) as LiveSearchCommitteeResult[];
    const seededMatch = slugMatches.find((match) => match.id === SMOKE_STAGE6_COMMITTEE_ID);
    if (seededMatch !== undefined) {
      const seededRecord = await fetchLiveCommitteeDiscoveryRecord(page, SMOKE_STAGE6_COMMITTEE_ID);
      return getSeededStage6CommitteeRoute(seededRecord.summary);
    }

    const liveSlugMatch = slugMatches.find(
      (match) =>
        typeof match.id === "string" &&
        typeof match.name === "string" &&
        match.name.toUpperCase() === SMOKE_STAGE6_COMMITTEE_NAME
    );
    if (liveSlugMatch !== undefined) {
      const liveCommitteeId = liveSlugMatch.id;
      if (typeof liveCommitteeId !== "string") {
        throw new Error("Live committee discovery: by-slug match is missing an id");
      }
      return buildDiscoveredLiveCommitteeAssertions(
        resolveDiscoveredCommitteeRouteId(liveSlugMatch),
        await fetchLiveCommitteeDiscoveryRecord(page, liveCommitteeId)
      );
    }
  }

  const searchResponse = await page.request.get(
    `${SMOKE_LIVE_API_BASE_URL}/v1/search?q=${encodeURIComponent(SMOKE_STAGE6_COMMITTEE_NAME)}&entity_type=committee`
  );
  if (!searchResponse.ok()) {
    throw new Error(
      `Live committee discovery failed: /v1/search returned ${searchResponse.status()} for query "${SMOKE_STAGE6_COMMITTEE_NAME}"`
    );
  }

  const searchBody = (await searchResponse.json()) as LiveSearchCommitteeResponse;
  const searchResults = Array.isArray(searchBody.items) ? searchBody.items : [];
  const match = searchResults.find(
    (candidate) =>
      typeof candidate.name === "string" &&
      candidate.name.toUpperCase() === SMOKE_STAGE6_COMMITTEE_NAME
  );
  if (match === undefined || typeof match.entity_id !== "string") {
    throw new Error(
      `Live committee discovery: search returned no committee named ${SMOKE_STAGE6_COMMITTEE_NAME}`
    );
  }

  return buildDiscoveredLiveCommitteeAssertions(
    match.entity_id,
    await fetchLiveCommitteeDiscoveryRecord(page, match.entity_id)
  );
}

// Candidate-list name search (lane B, aug18 findability).
// The /candidates name box hands off to /search with `q` alone, so this fixture
// is keyed on a query carrying no entity_type. The raw name is the shape FEC
// filings actually ship; the formatted one is what formatPersonDisplayName must
// put on screen. Digit-free on purpose: the candidate identity predicate in
// api/queries/campaign_finance.py rejects any name matching '[0-9]', which
// silently empties a browse list while a test still reports green.
export const SMOKE_CANDIDATE_NAME_SEARCH_QUERY = "ossoff";
export const SMOKE_CANDIDATE_NAME_SEARCH_RAW_NAME = "OSSOFF, T. JONATHAN";
export const SMOKE_CANDIDATE_NAME_SEARCH_FORMATTED_NAME = "Ossoff, T. Jonathan";
// Browse-list twin of the raw-cased search specimen (civibus-af3): since the
// in-place /candidates name filter replaced the /search handoff, the
// raw-vs-formatted proof has to run against a BROWSE row, so the candidate
// list fixture carries one item whose name ships in raw FEC casing. It sits
// last in the list on purpose: the unfiltered first page (limit 1) never shows
// it, which is what makes "the filter surfaced it" a discriminating assertion
// rather than one pagination could satisfy.
export const SMOKE_NAME_FILTER_CANDIDATE_ID = "fafafafa-fafa-4faf-8faf-fafafafafafa";
export const SMOKE_NAME_FILTER_CANDIDATE_SLUG = "ossoff-t-jonathan";
