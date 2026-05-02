import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import Layout from "./+layout.svelte";
import HomePage from "./+page.svelte";
import MethodologyPage from "./methodology/+page.svelte";
import ElectionPage from "./election/[date]/+page.svelte";
import CalendarPage from "./calendar/+page.svelte";
import CoveragePage from "./coverage/+page.svelte";
import DataSourcesPage from "./data-sources/+page.svelte";
import CandidatesPage from "./candidates/+page.svelte";
import CommitteesPage from "./committees/+page.svelte";
import PersonPage from "./person/[id]/+page.svelte";
import OrgPage from "./org/[id]/+page.svelte";
import PropertyPage from "./property/[id]/+page.svelte";
import OfficePage from "./office/[id]/+page.svelte";
import ContestPage from "./contest/[id]/+page.svelte";
import CandidacyPage from "./candidacy/[id]/+page.svelte";
import OfficeholdingPage from "./officeholding/[id]/+page.svelte";
import ErrorPage from "./+error.svelte";
import {
  COMMITTEE_TYPE_OPTIONS,
  FEC_CANDIDATE_OFFICE_OPTIONS,
  US_STATE_OPTIONS
} from "$lib/campaign-finance-detail/filter-options";
import { APP_SHELL } from "$lib/config/app";
import { createEmptyFeatureCollection } from "$lib/server/api/civic-geometry";

let currentPageUrl = new URL("https://civibus.test/");
type NavigatingTarget = { url: URL } | null;
type NavigatingValue = null | { from: NavigatingTarget; to: NavigatingTarget };
let currentNavigating: NavigatingValue = null;

vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: currentPageUrl });
      return () => {};
    }
  },
  navigating: {
    subscribe(run: (value: NavigatingValue) => void): () => void {
      run(currentNavigating);
      return () => {};
    }
  }
}));

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";
const PARCEL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const CANDIDACY_ID = "88888888-8888-4888-8888-888888888888";
const OFFICEHOLDING_ID = "44444444-4444-4444-8444-444444444444";
const ELECTORAL_DIVISION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const DEFAULT_OG_IMAGE = "https://civibus.test/og-default.png";

function expectDefaultShareHead(
  head: string,
  {
    canonicalPath,
    ogType,
    expectsJsonLd = true,
    expectsTwitterImage = true,
    expectsOgUrl = false
  }: {
    canonicalPath: string;
    ogType: string;
    expectsJsonLd?: boolean;
    expectsTwitterImage?: boolean;
    expectsOgUrl?: boolean;
  }
): void {
  expect(head).toContain(`<link rel="canonical" href="https://civibus.test${canonicalPath}"`);
  expect(head).toContain(`<meta property="og:type" content="${ogType}"`);
  expect(head).toContain(`<meta property="og:image" content="${DEFAULT_OG_IMAGE}"`);
  expect(head).toContain('<meta name="twitter:card" content="summary_large_image"');
  if (expectsTwitterImage) {
    expect(head).toContain(`<meta name="twitter:image" content="${DEFAULT_OG_IMAGE}"`);
  }
  if (expectsOgUrl) {
    expect(head).toContain(`<meta property="og:url" content="https://civibus.test${canonicalPath}"`);
  }
  if (expectsJsonLd) {
    expect(head).toContain('<script type="application/ld+json">');
    return;
  }
  expect(head).not.toContain("application/ld+json");
}

function expectNoRouteSocialTags(head: string): void {
  expect(head).not.toContain('<link rel="canonical"');
  expect(head).not.toContain('property="og:');
  expect(head).not.toContain('name="twitter:');
  expect(head).not.toContain("application/ld+json");
}

function expectOptionList(body: string, options: readonly { code: string; label: string }[]): void {
  for (const option of options) {
    expect(body).toContain(`value="${option.code}"`);
    expect(body).toContain(`>${option.label}</option>`);
  }
}

function expectListLoadingState(body: string, loadingLabel: string, emptyStateMessage: string): void {
  expect(body).toContain('role="status"');
  expect(body).toContain('aria-live="polite"');
  expect(body).toContain("Updating results");
  expect(body).toContain(`aria-label="${loadingLabel}"`);
  expect(body).toContain("skeleton-panel");
  expect(body).not.toContain(emptyStateMessage);
  expect(body).not.toContain("Showing 0–0");
}

function buildEntityPageData(entityType: "person" | "org", entityId: string, detail: object) {
  return {
    data: {
      entityType,
      detail,
      matches: Promise.resolve([]),
      relationships: Promise.resolve({
        entity_type: entityType,
        entity_id: entityId,
        neighbors: [],
        total_count: 0
      })
    }
  } as any;
}

function expectMarkers(markup: string, markers: readonly string[]): void {
  for (const marker of markers) {
    expect(markup).toContain(marker);
  }
}

const PERSON_DETAIL = {
  id: PERSON_ID,
  canonical_name: "Jane Doe",
  name_variants: [],
  first_name: "Jane",
  middle_name: null,
  last_name: "Doe",
  suffix: null,
  date_of_birth: null,
  year_of_birth: null,
  bio_text: null,
  bio_source_url: null,
  bio_license: null,
  bio_pulled_at: null,
  identifiers: {},
  primary_address_id: null,
  er_cluster_id: null,
  er_confidence: null,
  sources: []
};

const ORG_DETAIL = {
  id: ORG_ID,
  canonical_name: "Civibus Action Org",
  name_variants: [],
  org_type: "pac",
  identifiers: {},
  registered_state: "NC",
  formation_date: null,
  dissolution_date: null,
  primary_address_id: null,
  er_cluster_id: null,
  er_confidence: null,
  sources: []
};

const PROPERTY_PAGE_DATA = {
  id: PARCEL_ID,
  reid: "200000001",
  pin: "0999999999",
  site_address: "123 MAIN ST",
  property_description: "Single family home",
  city: "Durham",
  zoning_class: "R-20",
  land_class: "Residential",
  acreage: "1.2500",
  neighborhood: "Northside",
  fire_district: "Durham",
  is_pending: false,
  deed_date: "2024-01-15",
  deed_book: "1234",
  deed_page: "567",
  jurisdiction_id: null,
  sources: [],
  ownership: [],
  assessments: []
};

const OFFICE_PAGE_DATA = {
  id: OFFICE_ID,
  name: "North Carolina Governor",
  office_level: "state" as const,
  title: "Governor",
  jurisdiction_id: null,
  state: "NC",
  is_elected: true,
  number_of_seats: 1,
  current_officeholders: [],
  current_holder_card: null,
  officeholding_timeline: [],
  recent_contests: [],
  selected_electoral_division_id: null,
  selected_electoral_division_type: null,
  selected_electoral_division_state: null,
  incomplete_data_states: ["no_officeholder"] as Array<"no_officeholder" | "no_active_contest">,
  sources: []
};

const OFFICE_PAGE_PROPS = {
  office: OFFICE_PAGE_DATA,
  geometryByLevel: {
    state: createEmptyFeatureCollection(),
    county: createEmptyFeatureCollection(),
    congressional_district: createEmptyFeatureCollection()
  }
};

describe("route head rendering", () => {
  beforeEach(() => {
    currentPageUrl = new URL("https://preview.internal:5173/");
    currentNavigating = null;
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-21T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders layout-level og:site_name from the shared SEO defaults", () => {
    const rendered = render(Layout);

    expect(rendered.head).toContain('<meta property="og:site_name" content="Civibus"');
    expect(rendered.body).toContain("Universal public-records intelligence");
    expect(rendered.body).toContain('href="/"');
    expect(rendered.body).toContain('href="/search"');
    expect(rendered.body).toContain('href="/candidates"');
    expect(rendered.body).toContain('href="/committees"');
    expect(rendered.body).toContain('href="/methodology"');
    expect(rendered.body).toContain("<footer");
    expect(rendered.body).toContain('aria-label="Footer"');
    expect(rendered.body).toMatch(
      /<footer[^>]*>[\s\S]*aria-label="Footer"[\s\S]*href="\/methodology"[\s\S]*>Methodology<\/a>/
    );
    expect(rendered.body).toContain("Report a data issue");
    expect(rendered.body).toContain('role="progressbar"');
    expect(rendered.body).toContain('aria-valuenow="0"');
    expect(rendered.body).toContain('aria-busy="false"');
    expect(rendered.body).toContain("<main");
    expect(rendered.body).toContain('aria-busy="false"');
  });

  it("renders active shell loading state when navigation is in progress", () => {
    currentNavigating = {
      from: { url: new URL("https://preview.internal:5173/search") },
      to: { url: new URL("https://preview.internal:5173/person/11111111-1111-4111-8111-111111111111") }
    };
    const rendered = render(Layout);
    expect(rendered.body).toContain("navigation-progress--active");
    expect(rendered.body).toContain('aria-valuenow="100"');
    expect(rendered.body).toContain('aria-busy="true"');
  });

  it("renders homepage with shared canonical/OG/Twitter tags plus serialized homepage JSON-LD", () => {
    currentPageUrl = new URL("https://preview.internal:5173/?utm_source=newsletter");
    const rendered = render(HomePage, {
      props: {
        data: {
          geometry: { type: "FeatureCollection", features: [] },
          stateSummaries: []
        }
      }
    });
    expectDefaultShareHead(rendered.head, {
      canonicalPath: "/",
      ogType: "website",
      expectsOgUrl: true
    });
    expect(rendered.head).toContain(
      '<meta name="description" content="Investigate campaign-finance, civic office, and property records with source-linked evidence in Civibus search."'
    );
    expect(rendered.head).toContain('"@type":"WebSite"');
    expect(rendered.head).toContain('"url":"https://civibus.test/"');
    expect(rendered.body).toContain(
      "Trace people, organizations, committees, and offices across jurisdictions."
    );
    expect(rendered.body).toContain("Browse candidates");
    expect(rendered.body).toContain('href="/committees"');
    expect(rendered.body).toContain("Understand coverage");
  });

  it("renders methodology with shared canonical/OG/Twitter tags plus serialized methodology JSON-LD", () => {
    currentPageUrl = new URL("https://preview.internal:5173/methodology?tab=coverage");
    const rendered = render(MethodologyPage);
    expectDefaultShareHead(rendered.head, {
      canonicalPath: "/methodology",
      ogType: "article",
      expectsOgUrl: true
    });
    expect(rendered.head).toContain(
      '<meta name="description" content="Coverage scope, confidence labels, and source guidance for campaign-finance, civic office, and property records."'
    );
    expect(rendered.head).toContain('"@type":"Article"');
    expect(rendered.head).toContain('"url":"https://civibus.test/methodology"');
    expect(rendered.body).toContain(
      "Civibus combines campaign-finance, civic office, and property records in one search experience. Coverage varies by jurisdiction and is refreshed based on source cadence."
    );
    expect(rendered.body).toContain("Data freshness policy");
    expect(rendered.body).toContain(
      "Every surfaced record is tied to provenance metadata and source links so users can trace claims back to official filings or source systems."
    );
  });

  it("renders election-date page with slashless canonical URL and election JSON-LD", () => {
    currentPageUrl = new URL("https://preview.internal:5173/election/2026-11-03?tab=summary");
    const rendered = render(ElectionPage, {
      props: {
        data: {
          date: "2026-11-03",
          total_contests: 1,
          total_candidacies: 2,
          contests: [
            {
              contest_id: CONTEST_ID,
              office_id: OFFICE_ID,
              name: "Governor 2026 General Election",
              election_type: "general",
              office_name: "Governor",
              office_level: "state",
              state: "NC",
              jurisdiction_id: null,
              electoral_division_id: ELECTORAL_DIVISION_ID,
              candidate_count: 2,
              result_status: null,
              winning_person_name: null
            }
          ]
        }
      }
    });

    expectDefaultShareHead(rendered.head, {
      canonicalPath: "/election/2026-11-03",
      ogType: "website",
      expectsOgUrl: true
    });
    expect(rendered.head).toContain('"@type":"Election"');
    expect(rendered.head).toContain('"name":"Election 2026-11-03"');
    expect(rendered.head).toContain("Election results and contest overview");
    expect(rendered.body).toContain("Governor 2026 General Election");
  });

  it("renders calendar page with slashless canonical URL and shared static metadata", () => {
    currentPageUrl = new URL("https://preview.internal:5173/calendar?ref=footer");
    const rendered = render(CalendarPage, {
      props: {
        data: {
          timelineEntries: [
            {
              date: "2026-11-03",
              contests: [
                {
                  contest_id: CONTEST_ID,
                  office_id: OFFICE_ID,
                  name: "Governor 2026 General Election",
                  election_type: "general",
                  office_name: "Governor",
                  office_level: "state",
                  state: "NC",
                  jurisdiction_id: null,
                  electoral_division_id: ELECTORAL_DIVISION_ID,
                  candidate_count: 2,
                  result_status: null,
                  winning_person_name: null
                }
              ]
            }
          ]
        }
      }
    });

    expectDefaultShareHead(rendered.head, {
      canonicalPath: "/calendar",
      ogType: "website",
      expectsJsonLd: false,
      expectsOgUrl: true
    });
    expect(rendered.head).toContain("Election Calendar | Civibus");
    expect(rendered.body).toContain("Governor 2026 General Election");
  });

  it("renders coverage page with APP_SHELL static metadata and canonical route path", () => {
    currentPageUrl = new URL("https://preview.internal:5173/coverage?via=nav");
    const rendered = render(CoveragePage, {
      props: {
        data: { coverageRows: [] }
      }
    });

    expectDefaultShareHead(rendered.head, {
      canonicalPath: "/coverage",
      ogType: "website",
      expectsJsonLd: false,
      expectsOgUrl: true
    });
    expect(rendered.head).toContain(APP_SHELL.staticRoutes.coverage.title);
    expect(rendered.head).toContain(APP_SHELL.staticRoutes.coverage.description);
    expect(rendered.body).toContain("No runtime coverage rows are available right now.");
  });

  it("renders data-sources page with APP_SHELL static metadata and canonical route path", () => {
    currentPageUrl = new URL("https://preview.internal:5173/data-sources?via=nav");
    const rendered = render(DataSourcesPage, {
      props: {
        data: { dataSources: [] }
      }
    });

    expectDefaultShareHead(rendered.head, {
      canonicalPath: "/data-sources",
      ogType: "website",
      expectsJsonLd: false,
      expectsOgUrl: true
    });
    expect(rendered.head).toContain(APP_SHELL.staticRoutes.dataSources.title);
    expect(rendered.head).toContain(APP_SHELL.staticRoutes.dataSources.description);
    expect(rendered.body).toContain("No runtime data-source rows are available right now.");
  });

  it("renders candidates list with shared canonical/OG/Twitter tags, filter controls, and unchanged pagination links", () => {
    currentPageUrl = new URL(
      "https://preview.internal:5173/candidates?state=NC&office=S&offset=25&limit=25"
    );
    const rendered = render(CandidatesPage, {
      props: {
        data: {
          items: [
            {
              id: PERSON_ID,
              fec_candidate_id: "H0NC01001",
              name: "Jane Candidate",
              party: "DEM",
              office: "H",
              state: "NC",
              district: "01",
              slug: "jane-candidate",
              slug_is_unique: true
            }
          ],
          offset: 25,
          limit: 25,
          has_next: true
        }
      }
    });

    expectDefaultShareHead(rendered.head, {
      canonicalPath: "/candidates",
      ogType: "website",
      expectsJsonLd: false
    });
    expect(rendered.body).toContain('<h3 class="campaign-list__name');
    expect(rendered.body).toContain('href="/candidate/jane-candidate"');
    expect(rendered.body).toContain("DEM · H · NC-01");
    expect(rendered.body).toContain("Showing 26–26");
    expect(rendered.body).toContain('for="candidate-filter-state"');
    expect(rendered.body).toContain(">State</label>");
    expect(rendered.body).toContain('id="candidate-filter-state"');
    expect(rendered.body).toContain('name="state"');
    expect(rendered.body).toContain('for="candidate-filter-office"');
    expect(rendered.body).toContain(">Office</label>");
    expect(rendered.body).toContain('id="candidate-filter-office"');
    expect(rendered.body).toContain('name="office"');
    expect(rendered.body).toContain(">Apply filters</button>");
    expect(rendered.body).toContain('href="/candidates?limit=25"');
    expect(rendered.body).toMatch(/<option[^>]*value="NC"[^>]*selected[^>]*>/);
    expect(rendered.body).toMatch(/<option[^>]*value="S"[^>]*selected[^>]*>/);
    expectOptionList(rendered.body, US_STATE_OPTIONS);
    expectOptionList(rendered.body, FEC_CANDIDATE_OFFICE_OPTIONS);
    expect(rendered.body).toContain(
      'href="/candidates?state=NC&amp;office=S&amp;offset=0&amp;limit=25"'
    );
    expect(rendered.body).toContain(
      'href="/candidates?state=NC&amp;office=S&amp;offset=50&amp;limit=25"'
    );
  });

  it("renders committees list with shared canonical/OG/Twitter tags, filter controls, and filter-preserving pagination links", () => {
    currentPageUrl = new URL(
      "https://preview.internal:5173/committees?state=NC&committee_type=Q&offset=25&limit=25"
    );
    const rendered = render(CommitteesPage, {
      props: {
        data: {
          items: [
            {
              id: ORG_ID,
              fec_committee_id: "C12345678",
              name: "Civibus Committee",
              committee_type: "Q",
              party: "DEM",
              state: "NC",
              slug: "civibus-committee",
              slug_is_unique: true
            }
          ],
          offset: 25,
          limit: 25,
          has_next: true
        }
      }
    });

    expectDefaultShareHead(rendered.head, {
      canonicalPath: "/committees",
      ogType: "website",
      expectsJsonLd: false
    });
    expect(rendered.body).toContain('<h3 class="campaign-list__name');
    expect(rendered.body).toContain('href="/committee/civibus-committee"');
    expect(rendered.body).toContain("Q · DEM · NC");
    expect(rendered.body).toContain("Showing 26–26");
    expect(rendered.body).toContain('for="committee-filter-state"');
    expect(rendered.body).toContain(">State</label>");
    expect(rendered.body).toContain('id="committee-filter-state"');
    expect(rendered.body).toContain('name="state"');
    expect(rendered.body).toContain('for="committee-filter-type"');
    expect(rendered.body).toContain(">Committee type</label>");
    expect(rendered.body).toContain('id="committee-filter-type"');
    expect(rendered.body).toContain('name="committee_type"');
    expect(rendered.body).toContain(">Apply filters</button>");
    expect(rendered.body).toContain('href="/committees?limit=25"');
    expect(rendered.body).toMatch(/<option[^>]*value="NC"[^>]*selected[^>]*>/);
    expect(rendered.body).toMatch(/<option[^>]*value="Q"[^>]*selected[^>]*>/);
    expectOptionList(rendered.body, US_STATE_OPTIONS);
    expectOptionList(rendered.body, COMMITTEE_TYPE_OPTIONS);
    expect(rendered.body).toContain(
      'href="/committees?state=NC&amp;committee_type=Q&amp;offset=0&amp;limit=25"'
    );
    expect(rendered.body).toContain(
      'href="/committees?state=NC&amp;committee_type=Q&amp;offset=50&amp;limit=25"'
    );
  });

  it("renders person detail with shared canonical/OG/Twitter tags and one detail JSON-LD block", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/person/${PERSON_ID}?tab=graph`);
    const rendered = render(PersonPage, {
      props: buildEntityPageData("person", PERSON_ID, PERSON_DETAIL)
    });
    expectDefaultShareHead(rendered.head, {
      canonicalPath: `/person/${PERSON_ID}`,
      ogType: "profile",
      expectsTwitterImage: false
    });
    expect(rendered.head).toContain('"@type":"Person"');
    expect(rendered.head).toContain('"@type":"BreadcrumbList"');
    expect(rendered.head).toContain('"name":"Jane Doe"');
  });

  it("renders person detail trust section with freshness severity, source labels, and dual-date summary", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/person/${PERSON_ID}`);
    const rendered = render(PersonPage, {
      props: {
        data: {
          entityType: "person",
          detail: {
            ...PERSON_DETAIL,
            sources: [
              {
                domain: "campaign_finance",
                jurisdiction: "federal/fec",
                data_source_name: "FEC",
                data_source_url: "https://www.fec.gov",
                source_record_key: "H0NC01001",
                record_url: "https://www.fec.gov/data/candidate/H0NC01001/",
                pull_date: "2026-03-20T00:00:00Z"
              },
              {
                domain: "campaign_finance",
                jurisdiction: "state/NC",
                data_source_name: "NC State Board",
                data_source_url: "https://www.ncsbe.gov",
                source_record_key: null,
                record_url: null,
                pull_date: "2026-03-19T00:00:00Z"
              }
            ]
          },
          matches: Promise.resolve([]),
          relationships: Promise.resolve({
            entity_type: "person",
            entity_id: PERSON_ID,
            neighbors: [],
            total_count: 0
          }),
          personCivicHistory: Promise.resolve({
            officeholdings: [],
            candidacies: [],
            officeholdingLabelsById: {},
            officeLabelsById: {},
            candidacyLabelsById: {},
            contestLabelsById: {}
          }),
          personFinanceSections: Promise.resolve([])
        }
      }
    });

    // Heading
    expect(rendered.body).toContain("Source and freshness");
    // Freshness severity text (fresh — within 7 days)
    expect(rendered.body).toContain("Data is current");
    // Dual-date last-pulled summary (freshest is 2026-03-20)
    expect(rendered.body).toContain("1 day ago");
    expect(rendered.body).toContain("2026-03-20");
    // Source labels
    expect(rendered.body).toContain("FEC (campaign_finance/federal/fec)");
    expect(rendered.body).toContain("NC State Board (campaign_finance/state/NC)");
    // Record key with redesigned label
    expect(rendered.body).toContain("Source record ID:");
    // Source link
    expect(rendered.body).toContain("View source record");
    expect(rendered.body).toContain('href="https://www.fec.gov/data/candidate/H0NC01001/"');
    // Row without record_url keeps a visible non-link affordance.
    expect((rendered.body.match(/View source record/g) ?? []).length).toBe(2);
    expect(rendered.body).toContain('href="https://www.ncsbe.gov/"');
    expect(rendered.body).not.toContain("Source record link unavailable.");
  });

  it("renders a person civic record section from candidacy/officeholding relationships without replacing entity internals", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/person/${PERSON_ID}`);
    const rendered = render(PersonPage, {
      props: {
        data: {
          entityType: "person",
          detail: PERSON_DETAIL,
          matches: Promise.resolve([]),
          relationships: Promise.resolve({
            entity_type: "person",
            entity_id: PERSON_ID,
            neighbors: [
              {
                entity_type: "candidacy",
                entity_id: CANDIDACY_ID,
                name: "Jane Doe candidacy",
                relationship_type: "CANDIDACY_OF",
                direction: "outbound" as const
              },
              {
                entity_type: "officeholding",
                entity_id: OFFICEHOLDING_ID,
                name: "Jane Doe officeholding",
                relationship_type: "HOLDS",
                direction: "outbound" as const
              },
              {
                entity_type: "contest",
                entity_id: CONTEST_ID,
                name: "NC-01 General",
                relationship_type: "RUNS_IN",
                direction: "outbound" as const
              },
              {
                entity_type: "office",
                entity_id: OFFICE_ID,
                name: "US House NC-01",
                relationship_type: "HOLDS",
                direction: "outbound" as const
              }
            ],
            total_count: 4
          }),
          personCivicHistory: Promise.resolve({
            officeholdings: [],
            candidacies: [],
            officeholdingLabelsById: {},
            officeLabelsById: {},
            candidacyLabelsById: {},
            contestLabelsById: {}
          }),
          personFinanceSections: Promise.resolve([])
        }
      }
    });

    // Deferred sections render skeleton placeholders during SSR; resolved content streams in after hydration
    expect(rendered.body).toContain('aria-label="Civic Record"');
    expect(rendered.body).toContain('aria-busy="true"');
    expect(rendered.body).toContain("skeleton-panel");
    // Entity internals also deferred
    expect(rendered.body).toContain('aria-label="Entity internals"');
  });

  it("renders office detail trust section with unknown freshness when sources have no parseable dates", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/office/${OFFICE_ID}`);
    const rendered = render(OfficePage, {
      props: {
        data: {
          ...OFFICE_PAGE_PROPS,
          office: {
            ...OFFICE_PAGE_PROPS.office,
            sources: [
              {
                domain: "civic",
                jurisdiction: "state/NC",
                data_source_name: "NC Civic Data",
                data_source_url: "https://example.org/nc",
                source_record_key: "gov-nc",
                record_url: null,
                pull_date: "not-a-date"
              }
            ]
          }
        }
      }
    });

    expect(rendered.body).toContain("Data freshness could not be determined");
    expect(rendered.body).toContain("Source and freshness");
  });

  it("renders organization detail with shared canonical/OG/Twitter tags and one detail JSON-LD block", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/org/${ORG_ID}?tab=graph`);
    const rendered = render(OrgPage, {
      props: buildEntityPageData("org", ORG_ID, ORG_DETAIL)
    });
    expectDefaultShareHead(rendered.head, { canonicalPath: `/org/${ORG_ID}`, ogType: "website" });
    expectMarkers(rendered.head, ['"@type":"Organization"', '"@type":"BreadcrumbList"', '"name":"Civibus Action Org"']);
    expectMarkers(rendered.body, ['aria-label="Breadcrumb"']);
  });

  it("renders property detail with shared canonical/OG/Twitter tags and one detail JSON-LD block", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/property/${PARCEL_ID}?tab=history`);
    const rendered = render(PropertyPage, { props: { data: PROPERTY_PAGE_DATA } });
    expectDefaultShareHead(rendered.head, { canonicalPath: `/property/${PARCEL_ID}`, ogType: "website" });
    expectMarkers(rendered.head, ['"@type":"Place"', '"@type":"BreadcrumbList"', '"name":"123 MAIN ST"']);
    expectMarkers(rendered.body, ['aria-label="Breadcrumb"']);
  });

  it("renders office detail with shared canonical/OG/Twitter tags and one detail JSON-LD block", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/office/${OFFICE_ID}?tab=history`);
    const rendered = render(OfficePage, { props: { data: OFFICE_PAGE_PROPS } });
    expectDefaultShareHead(rendered.head, { canonicalPath: `/office/${OFFICE_ID}`, ogType: "website" });
    expectMarkers(rendered.head, ['"@type":"GovernmentOffice"', '"@type":"BreadcrumbList"', '"name":"North Carolina Governor"']);
    expectMarkers(rendered.body, ['aria-label="Breadcrumb"']);
  });

  it("renders contest detail with shared canonical/OG/Twitter tags, Election JSON-LD type, and breadcrumb graph payload", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/contest/${CONTEST_ID}?tab=history`);
    const rendered = render(ContestPage, {
      props: {
        data: {
          contest: {
            id: CONTEST_ID,
            name: "Governor 2026 General Election",
            election_date: "2026-11-03",
            election_type: "general",
            office_id: OFFICE_ID,
            electoral_division_id: ELECTORAL_DIVISION_ID,
            number_of_seats: 1,
            filing_deadline: "2026-09-01",
            is_partisan: true,
            candidate_list_incomplete: false,
            candidacies: [],
            sources: []
          },
          geometryByLevel: {
            state: createEmptyFeatureCollection(),
            county: createEmptyFeatureCollection(),
            congressional_district: createEmptyFeatureCollection()
          },
          contestCandidateFinanceByPersonId: {}
        }
      }
    });
    expectDefaultShareHead(rendered.head, { canonicalPath: `/contest/${CONTEST_ID}`, ogType: "website" });
    expectMarkers(rendered.head, ['"@graph"', '"@type":"Election"', '"@type":"BreadcrumbList"']);
    expectMarkers(rendered.body, ['aria-label="Breadcrumb"']);
  });

  it("renders candidacy detail with shared canonical/OG/Twitter tags, Role JSON-LD type, and breadcrumb graph payload", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/candidacy/${CANDIDACY_ID}?tab=history`);
    const rendered = render(CandidacyPage, {
      props: {
        data: {
          id: CANDIDACY_ID,
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          contest_id: CONTEST_ID,
          party: "DEM",
          filing_date: "2026-02-01",
          status: "filed",
          incumbent_challenge: "I",
          candidate_number: "17",
          sources: []
        }
      }
    });
    expectDefaultShareHead(rendered.head, { canonicalPath: `/candidacy/${CANDIDACY_ID}`, ogType: "profile" });
    expectMarkers(rendered.head, ['"@graph"', '"@type":"Role"', '"@type":"BreadcrumbList"']);
    expectMarkers(rendered.body, ['aria-label="Breadcrumb"']);
  });

  it("renders officeholding detail with shared canonical/OG/Twitter tags, Role JSON-LD type, and breadcrumb graph payload", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/officeholding/${OFFICEHOLDING_ID}?tab=history`);
    const rendered = render(OfficeholdingPage, {
      props: {
        data: {
          id: OFFICEHOLDING_ID,
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          office_id: OFFICE_ID,
          electoral_division_id: ELECTORAL_DIVISION_ID,
          holder_status: "elected",
          valid_period_lower: "2025-01-01",
          valid_period_upper: null,
          date_precision: "day",
          sources: []
        }
      }
    });
    expectDefaultShareHead(rendered.head, { canonicalPath: `/officeholding/${OFFICEHOLDING_ID}`, ogType: "website" });
    expectMarkers(rendered.head, ['"@graph"', '"@type":"Role"', '"@type":"BreadcrumbList"']);
    expectMarkers(rendered.body, ['aria-label="Breadcrumb"']);
  });

  it("renders +error with status-bucket framing, noindex metadata, recovery links, and no route-level social/structured tags", () => {
    const cases = [
      {
        status: 404,
        expectedTitle: "Page not found",
        expectedHeading: "Page not found",
        expectedSummary:
          "The page may have moved, been removed, or the URL may be incorrect.",
        expectedDescription:
          "The requested page could not be found. Try search or return to the homepage."
      },
      {
        status: 422,
        expectedTitle: "Request could not be completed",
        expectedHeading: "Request could not be completed",
        expectedSummary:
          "The server rejected this request. Check the URL or try searching for a record.",
        expectedDescription:
          "The request could not be completed. Review your input or try another page."
      },
      {
        status: 503,
        expectedTitle: "Service temporarily unavailable",
        expectedHeading: "Service temporarily unavailable",
        expectedSummary:
          "Civibus is having trouble loading this page right now. Please try again shortly.",
        expectedDescription:
          "Civibus could not complete this request because a service is unavailable."
      },
      {
        status: 302,
        expectedTitle: "Unexpected response status",
        expectedHeading: "Unexpected response status",
        expectedSummary:
          "This response status is not recognized by the route-level error buckets.",
        expectedDescription:
          "Civibus received an unexpected response status for this request."
      }
    ];

    for (const testCase of cases) {
      const rendered = render(ErrorPage, {
        props: {
          status: testCase.status,
          error: {
            detail: [
              { loc: ["query", "q"], msg: "required" },
              { loc: ["query", "entity_type"], msg: "invalid value" }
            ]
          } as unknown as App.Error
        }
      });

      expect(rendered.head).toContain(`<title>${testCase.expectedTitle} | Civibus</title>`);
      expect(rendered.head).toContain(
        `<meta name="description" content="${testCase.expectedDescription}"`
      );
      expect(rendered.head).toContain('<meta name="robots" content="noindex"');
      expectNoRouteSocialTags(rendered.head);
      expect(rendered.body).toContain(testCase.expectedHeading);
      expect(rendered.body).toContain(testCase.expectedSummary);
      expect(rendered.body).toContain(`HTTP ${testCase.status}`);
      expect(rendered.body).toContain("query.q: required; query.entity_type: invalid value");
      expect(rendered.body).toContain("Return home");
      expect(rendered.body).toContain("Go to search");
      expect(rendered.body).toContain('href="/"');
      expect(rendered.body).toContain('href="/search"');
    }
  });

  for (const testCase of [
    {
      title: "renders candidates list loading indicator during same-route filter navigation",
      url: "https://preview.internal:5173/candidates?state=NC",
      navigatingTo: "https://preview.internal:5173/candidates?state=GA",
      page: CandidatesPage as any,
      loadingLabel: "Candidate results loading",
      emptyStateMessage: "No candidates found for the selected filters."
    },
    {
      title: "renders committees list loading indicator during same-route filter navigation",
      url: "https://preview.internal:5173/committees?state=NC",
      navigatingTo: "https://preview.internal:5173/committees?state=NC&committee_type=Q",
      page: CommitteesPage as any,
      loadingLabel: "Committee results loading",
      emptyStateMessage: "No committees found for the selected filters."
    }
  ]) {
    it(testCase.title, () => {
      currentPageUrl = new URL(testCase.url);
      currentNavigating = {
        from: { url: new URL(testCase.url) },
        to: { url: new URL(testCase.navigatingTo) }
      };
      const rendered = render(testCase.page, {
        props: { data: { items: [], offset: 0, limit: 25, has_next: false } }
      });
      expectListLoadingState(rendered.body, testCase.loadingLabel, testCase.emptyStateMessage);
    });
  }
});
