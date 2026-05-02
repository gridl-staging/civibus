// @ts-expect-error Smoke fixtures run under Node ESM and import the TS module directly.
import { resolveSmokeApiPort } from "../../src/lib/server/api/smoke-port.ts";

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
export const SMOKE_PROPERTY_ID = "66666666-6666-4666-8666-666666666666";
export const SMOKE_COMMITTEE_SLUG = process.env.SMOKE_COMMITTEE_SLUG ?? "citizens-for-civibus";
export const SMOKE_CANDIDATE_SLUG = "pat-candidate";
export const SMOKE_COLLIDING_COMMITTEE_SLUG = "shared-committee";
export const SMOKE_COLLIDING_CANDIDATE_SLUG = "shared-candidate";
export const SMOKE_COLLIDING_COMMITTEE_ID = "77777777-7777-4777-8777-777777777777";
export const SMOKE_COLLIDING_CANDIDATE_ID = "88888888-8888-4888-8888-888888888888";
export const SMOKE_EMPTY_COMMITTEE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
export const SMOKE_EMPTY_CANDIDATE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
export const SMOKE_DEVIANT_CANDIDATE_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
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
export const SMOKE_SEARCH_CANDIDATE_QUERY = "jane";
export const SMOKE_SEARCH_CANDIDATE_RESULT_NAME = "Jane Doe";
export const SMOKE_SEARCH_CONTEST_QUERY = "senate";
export const SMOKE_SEARCH_CONTEST_RESULT_NAME = "2026 NC Senate General";
export const SMOKE_SEARCH_EMPTY_TITLE = "Search | Civibus";
export const SMOKE_SEARCH_EMPTY_DESCRIPTION =
  "Search people, organizations, committees, candidates, offices, and contests across campaign-finance and civic records.";
export const SMOKE_SEARCH_TITLE = "civ (1 result) | Search | Civibus";
export const SMOKE_SEARCH_DESCRIPTION = '1 result for "civ" across Civibus records.';
export const SMOKE_HOME_TITLE = "Civibus | Public-records intelligence for journalists";
export const SMOKE_HOME_DESCRIPTION =
  "Investigate campaign-finance, civic office, and property records with source-linked evidence in Civibus search.";
export const SMOKE_HOME_HEADING = "Trace people, organizations, committees, and offices across jurisdictions.";
export const SMOKE_HOME_COVERAGE_HEADING = "Coverage at a glance";
export const SMOKE_HOME_COVERAGE_SUMMARY =
  "Coverage spans federal and state campaign-finance records, civic offices, and a property pilot. See methodology for current operational scope by jurisdiction.";
export const SMOKE_LANDING_MAP_HEADING = "Browse coverage by state";
export const SMOKE_LANDING_MAP_SUPPORTED_STATE_NAME = "North Carolina";
export const SMOKE_LANDING_MAP_SUPPORTED_STATE_CODE = "NC";
export const SMOKE_LANDING_MAP_UNSUPPORTED_STATE_NAME = "Arkansas";
export const SMOKE_LANDING_MAP_UNSUPPORTED_LABEL = "Coverage not yet available";
export const SMOKE_LANDING_MAP_WARNING_STATE_NAME = "Minnesota";
export const SMOKE_LANDING_MAP_WARNING_TEXT =
  "Quarterly bulk only; refresh cadence below weekly target.";
export const SMOKE_STATE_DETAIL_SUPPORTED_CODE = "NC";
export const SMOKE_STATE_DETAIL_SUPPORTED_NAME = "North Carolina";
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
export const SMOKE_METHODOLOGY_TITLE = "Methodology | Civibus";
export const SMOKE_METHODOLOGY_DESCRIPTION =
  "Coverage scope, confidence labels, and source guidance for campaign-finance, civic office, and property records.";
export const SMOKE_METHODOLOGY_SECTION_HEADING = "Data freshness policy";
export const SMOKE_METHODOLOGY_SECTION_BODY =
  "Production support requires data that can be refreshed at least weekly near elections, with daily updates preferred. Sources that only publish annual or quarterly exports are not treated as fully launch-ready without a supplementary path.";
export const SMOKE_METHODOLOGY_CONFIDENCE_HEADING = "Entity resolution confidence labels";
export const SMOKE_SHELL_NAV_HOME = "Home";
export const SMOKE_SHELL_NAV_SEARCH = "Search";
export const SMOKE_SHELL_NAV_CANDIDATES = "Candidates";
export const SMOKE_SHELL_NAV_COMMITTEES = "Committees";
export const SMOKE_SHELL_NAV_METHODOLOGY = "Methodology";
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

export const SMOKE_PERSON_CANONICAL_NAME = "Jane Doe";
export const SMOKE_PERSON_NO_PORTRAIT_CANONICAL_NAME = "Jordan No Portrait";
export const SMOKE_PERSON_MISSING_PORTRAIT_CANONICAL_NAME = "Avery Missing Portrait";
export const SMOKE_PERSON_RELATIONSHIP_NAME = "Q1 Filing";
export const SMOKE_PERSON_GRAPH_ORG_NAME = "Action PAC";
export const SMOKE_PERSON_TITLE = "Jane Doe | Person | Civibus";
export const SMOKE_PERSON_DESCRIPTION =
  "Person profile with 1 identifier and source-linked records.";
export const SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID = "entity-portrait-image";
export const SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID = "entity-portrait-silhouette";

export const SMOKE_ORG_CANONICAL_NAME = "Civibus Action Org";
export const SMOKE_ORG_RELATIONSHIP_NAME = "Org Filing 2026-Q1";
export const SMOKE_ORG_TITLE = "Civibus Action Org | Organization | Civibus";
export const SMOKE_ORG_DESCRIPTION =
  "Organization profile with 1 identifier and source-linked records.";

export const SMOKE_COMMITTEE_NAME = "Citizens for Civibus";
export const SMOKE_PHL_COMMITTEE_NAME = "Philadelphia Transit Neighbors";
export const SMOKE_CANDIDATE_NAME = "Pat Candidate";
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
export const SMOKE_COMMITTEE_FILING_SUMMARY_EMPTY_STATE = "No filing-period fundraising data available.";
export const SMOKE_COMMITTEE_ORG_LINK_TEXT = `Organization record (${SMOKE_ORG_ID})`;
export const SMOKE_COMMITTEE_CONTRIBUTOR_PERSON_LINK_TEXT = "View contributor person record";
export const SMOKE_COMMITTEE_CONTRIBUTOR_ORG_LINK_TEXT = "View contributor organization record";
export const SMOKE_COMMITTEE_RECIPIENT_CANDIDATE_LINK_TEXT = "View recipient candidate record";
export const SMOKE_COMMITTEE_RECIPIENT_COMMITTEE_LINK_TEXT = "View recipient committee record";
export const SMOKE_CANDIDATE_TITLE = "Pat Candidate | Candidate | Civibus";
export const SMOKE_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";
export const SMOKE_CANDIDATES_TITLE = "Candidates | Civibus";
export const SMOKE_CANDIDATES_DESCRIPTION = "Campaign-finance candidates with server-rendered pagination.";
export const SMOKE_CANDIDATE_TOTAL_RAISED = "$250.00";
export const SMOKE_CANDIDATE_TOTAL_SPENT = "$80.00";
export const SMOKE_CANDIDATE_NET_TOTAL = "$170.00";
export const SMOKE_CANDIDATE_DATA_THROUGH = "2026-03-19";
export const SMOKE_CANDIDATE_PERSON_LINK_TEXT = `Person record (${SMOKE_PERSON_ID})`;
export const SMOKE_CANDIDATE_COMMITTEE_LINK_TEXT = `Committee record (${SMOKE_COMMITTEE_ID})`;
export const SMOKE_EMPTY_COMMITTEE_TITLE = "Committee Empty | Committee | Civibus";
export const SMOKE_EMPTY_COMMITTEE_DESCRIPTION = "Committee profile from campaign-finance records.";
export const SMOKE_EMPTY_CANDIDATE_TITLE = "Candidate Empty | Candidate | Civibus";
export const SMOKE_EMPTY_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";
export const SMOKE_DEVIANT_CANDIDATE_TITLE = "Candidate Deviant | Candidate | Civibus";
export const SMOKE_DEVIANT_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";
export const SMOKE_AL_CANDIDATE_TITLE = "Candidate Alabama | Candidate | Civibus";
export const SMOKE_AL_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";
export const SMOKE_GA_CANDIDATE_TITLE = "Candidate Georgia | Candidate | Civibus";
export const SMOKE_GA_CANDIDATE_DESCRIPTION = "Candidate profile from campaign-finance records.";

export const SMOKE_IE_COMMITTEE_A_ID = "dd111111-1111-4111-8111-111111111111";
export const SMOKE_IE_COMMITTEE_A_NAME = "Super PAC Alpha";
export const SMOKE_IE_TRANSACTION_DISSEMINATION_DATE = "2026-03-20";
export const SMOKE_CANDIDATE_SUPPORT_TOTAL = "$15,000.00";
export const SMOKE_CANDIDATE_OPPOSE_TOTAL = "$8,500.00";
export const SMOKE_CANDIDATE_OUTSIDE_SPENDING_EMPTY =
  "Outside-spending data is not yet available for this candidate. Coverage may be incomplete.";
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
// docs/research/in_freshness_recheck_2026_04_26.md.
export const SMOKE_PROPERTY_PROVENANCE_SOURCE_NAME = "Durham County (property/us/nc/durham)";
export const SMOKE_PROVENANCE_LAST_PULLED = /^Last pulled: (?:today|\d+ days? ago) \(\d{4}-\d{2}-\d{2}\)$/;
export const SMOKE_PROVENANCE_SOURCE_KEY = "Source record ID: person-1";
export const SMOKE_PROPERTY_PROVENANCE_SOURCE_KEY = "Source record ID: parcel-1";
export const SMOKE_TRUST_ADVISORY = "Review source records before publication.";
export const SMOKE_TRUST_EMPTY_MESSAGE = "No source records are available for this detail yet.";
export const SMOKE_TRUST_LAST_PULLED_UNAVAILABLE = "Last pulled: unavailable";
export const SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING = "Campaign finance";
export const SMOKE_PERSON_LINKED_COMMITTEES_HEADING = "Linked committees";
export const SMOKE_PERSON_DONORS_AND_VENDORS_HEADING = "Donors and vendors";
export const SMOKE_PERSON_OUTSIDE_SPENDING_HEADING = "Outside Spending";
export const SMOKE_COMMITTEE_EMPTY_STATE = "No recent committee transactions found.";
export const SMOKE_GRAPH_EMPTY_STATE = "No graph relationships are available yet. Linked records will appear after future ingests.";
export const SMOKE_ER_EMPTY_STATE = "No entity-resolution matches are available yet. Check back after the next ER refresh.";
export const SMOKE_TECHNICAL_DISCLOSURE_SUMMARY = "Entity-resolution and graph internals";
export const SMOKE_PROPERTY_EMPTY_OWNERSHIP_STATE = "No ownership history is available yet. Check back after the next county refresh.";
export const SMOKE_PROPERTY_EMPTY_ASSESSMENT_STATE = "No assessment history is available yet. Check back after the next county refresh.";
export const SMOKE_OFFICEHOLDER_EMPTY_STATE = "No current officeholders are linked yet. Check back after the next records refresh.";
