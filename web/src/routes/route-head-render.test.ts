import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import Layout from "./+layout.svelte";
import HomePage from "./+page.svelte";
import MethodologyPage from "./methodology/+page.svelte";
import CandidatesPage from "./candidates/+page.svelte";
import CommitteesPage from "./committees/+page.svelte";
import PersonPage from "./person/[id]/+page.svelte";
import OrgPage from "./org/[id]/+page.svelte";
import PropertyPage from "./property/[id]/+page.svelte";
import OfficePage from "./office/[id]/+page.svelte";
import ContestPage from "./contest/[id]/+page.svelte";
import CandidacyPage from "./candidacy/[id]/+page.svelte";
import OfficeholdingPage from "./officeholding/[id]/+page.svelte";
import SearchPage from "./search/+page.svelte";
import ErrorPage from "./+error.svelte";

let currentPageUrl = new URL("https://civibus.test/");
let currentNavigating: null | { from: URL; to: URL } = null;

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
    subscribe(run: (value: null | { from: URL; to: URL }) => void): () => void {
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
      from: new URL("https://preview.internal:5173/search"),
      to: new URL("https://preview.internal:5173/person/11111111-1111-4111-8111-111111111111")
    };
    const rendered = render(Layout);

    expect(rendered.body).toContain("navigation-progress--active");
    expect(rendered.body).toContain('aria-valuenow="100"');
    expect(rendered.body).toContain('aria-busy="true"');
  });

  it("renders homepage with shared canonical/OG/Twitter tags plus serialized homepage JSON-LD", () => {
    currentPageUrl = new URL("https://preview.internal:5173/?utm_source=newsletter");
    const rendered = render(HomePage);

    expect(rendered.head).toContain('<link rel="canonical" href="https://civibus.test/"');
    expect(rendered.head).toContain('<meta property="og:type" content="website"');
    expect(rendered.head).toContain('<meta property="og:url" content="https://civibus.test/"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<meta name="twitter:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain(
      '<meta name="description" content="Investigate campaign-finance, civic office, and property records with source-linked evidence in Civibus search."'
    );
    expect(rendered.head).toContain('<script type="application/ld+json">');
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

    expect(rendered.head).toContain('<link rel="canonical" href="https://civibus.test/methodology"');
    expect(rendered.head).toContain('<meta property="og:type" content="article"');
    expect(rendered.head).toContain('<meta property="og:url" content="https://civibus.test/methodology"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<meta name="twitter:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain(
      '<meta name="description" content="Coverage scope, confidence labels, and source guidance for campaign-finance, civic office, and property records."'
    );
    expect(rendered.head).toContain('<script type="application/ld+json">');
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

  it("renders candidates list with shared canonical/OG/Twitter tags, no JSON-LD, and unchanged pagination links", () => {
    currentPageUrl = new URL("https://preview.internal:5173/candidates?state=NC&offset=25&limit=25");
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

    expect(rendered.head).toContain('<link rel="canonical" href="https://civibus.test/candidates"');
    expect(rendered.head).toContain('<meta property="og:type" content="website"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<meta name="twitter:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).not.toContain("application/ld+json");
    expect(rendered.body).toContain('href="/candidates?state=NC&amp;offset=0&amp;limit=25"');
    expect(rendered.body).toContain('href="/candidates?state=NC&amp;offset=50&amp;limit=25"');
  });

  it("renders committees list with shared canonical/OG/Twitter tags, no JSON-LD, and unchanged pagination links", () => {
    currentPageUrl = new URL("https://preview.internal:5173/committees?state=NC&offset=0&limit=25");
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
          offset: 0,
          limit: 25,
          has_next: true
        }
      }
    });

    expect(rendered.head).toContain('<link rel="canonical" href="https://civibus.test/committees"');
    expect(rendered.head).toContain('<meta property="og:type" content="website"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<meta name="twitter:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).not.toContain("application/ld+json");
    expect(rendered.body).not.toContain(">Previous<");
    expect(rendered.body).toContain('href="/committees?state=NC&amp;offset=25&amp;limit=25"');
  });

  it("renders person detail with shared canonical/OG/Twitter tags and one detail JSON-LD block", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/person/${PERSON_ID}?tab=graph`);
    const rendered = render(PersonPage, {
      props: {
        data: {
          entityType: "person",
          detail: {
            id: PERSON_ID,
            canonical_name: "Jane Doe",
            name_variants: [],
            first_name: "Jane",
            middle_name: null,
            last_name: "Doe",
            suffix: null,
            date_of_birth: null,
            year_of_birth: null,
            identifiers: {},
            primary_address_id: null,
            er_cluster_id: null,
            er_confidence: null,
            sources: []
          },
          matches: Promise.resolve([]),
          relationships: Promise.resolve({
            entity_type: "person",
            entity_id: PERSON_ID,
            neighbors: [],
            total_count: 0
          })
        }
      }
    });

    expect(rendered.head).toContain(`<link rel="canonical" href="https://civibus.test/person/${PERSON_ID}"`);
    expect(rendered.head).toContain('<meta property="og:type" content="profile"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<script type="application/ld+json">');
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
            id: PERSON_ID,
            canonical_name: "Jane Doe",
            name_variants: [],
            first_name: "Jane",
            middle_name: null,
            last_name: "Doe",
            suffix: null,
            date_of_birth: null,
            year_of_birth: null,
            identifiers: {},
            primary_address_id: null,
            er_cluster_id: null,
            er_confidence: null,
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
          })
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
    expect((rendered.body.match(/View source record/g) ?? []).length).toBe(1);
    expect(rendered.body).toContain("Source record link unavailable.");
  });

  it("renders a person civic record section from candidacy/officeholding relationships without replacing entity internals", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/person/${PERSON_ID}`);
    const rendered = render(PersonPage, {
      props: {
        data: {
          entityType: "person",
          detail: {
            id: PERSON_ID,
            canonical_name: "Jane Doe",
            name_variants: [],
            first_name: "Jane",
            middle_name: null,
            last_name: "Doe",
            suffix: null,
            date_of_birth: null,
            year_of_birth: null,
            identifiers: {},
            primary_address_id: null,
            er_cluster_id: null,
            er_confidence: null,
            sources: []
          },
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
          })
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
          id: OFFICE_ID,
          name: "North Carolina Governor",
          office_level: "state",
          title: "Governor",
          jurisdiction_id: null,
          state: "NC",
          is_elected: true,
          number_of_seats: 1,
          current_officeholders: [],
          incomplete_data_states: ["no_officeholder"],
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
    });

    expect(rendered.body).toContain("Data freshness could not be determined");
    expect(rendered.body).toContain("Source and freshness");
  });

  it("renders organization detail with shared canonical/OG/Twitter tags and one detail JSON-LD block", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/org/${ORG_ID}?tab=graph`);
    const rendered = render(OrgPage, {
      props: {
        data: {
          entityType: "org",
          detail: {
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
          },
          matches: Promise.resolve([]),
          relationships: Promise.resolve({
            entity_type: "org",
            entity_id: ORG_ID,
            neighbors: [],
            total_count: 0
          })
        }
      }
    });

    expect(rendered.head).toContain(`<link rel="canonical" href="https://civibus.test/org/${ORG_ID}"`);
    expect(rendered.head).toContain('<meta property="og:type" content="website"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<script type="application/ld+json">');
    expect(rendered.head).toContain('"@type":"Organization"');
    expect(rendered.head).toContain('"@type":"BreadcrumbList"');
    expect(rendered.head).toContain('"name":"Civibus Action Org"');
    expect(rendered.body).toContain('aria-label="Breadcrumb"');
  });

  it("renders property detail with shared canonical/OG/Twitter tags and one detail JSON-LD block", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/property/${PARCEL_ID}?tab=history`);
    const rendered = render(PropertyPage, {
      props: {
        data: {
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
        }
      }
    });

    expect(rendered.head).toContain(`<link rel="canonical" href="https://civibus.test/property/${PARCEL_ID}"`);
    expect(rendered.head).toContain('<meta property="og:type" content="website"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<script type="application/ld+json">');
    expect(rendered.head).toContain('"@type":"Place"');
    expect(rendered.head).toContain('"@type":"BreadcrumbList"');
    expect(rendered.head).toContain('"name":"123 MAIN ST"');
    expect(rendered.body).toContain('aria-label="Breadcrumb"');
  });

  it("renders office detail with shared canonical/OG/Twitter tags and one detail JSON-LD block", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/office/${OFFICE_ID}?tab=history`);
    const rendered = render(OfficePage, {
      props: {
        data: {
          id: OFFICE_ID,
          name: "North Carolina Governor",
          office_level: "state",
          title: "Governor",
          jurisdiction_id: null,
          state: "NC",
          is_elected: true,
          number_of_seats: 1,
          current_officeholders: [],
          incomplete_data_states: ["no_officeholder"],
          sources: []
        }
      }
    });

    expect(rendered.head).toContain(`<link rel="canonical" href="https://civibus.test/office/${OFFICE_ID}"`);
    expect(rendered.head).toContain('<meta property="og:type" content="website"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<script type="application/ld+json">');
    expect(rendered.head).toContain('"@type":"GovernmentOffice"');
    expect(rendered.head).toContain('"@type":"BreadcrumbList"');
    expect(rendered.head).toContain('"name":"North Carolina Governor"');
    expect(rendered.body).toContain('aria-label="Breadcrumb"');
  });

  it("renders contest detail with shared canonical/OG/Twitter tags, Election JSON-LD type, and breadcrumb graph payload", () => {
    currentPageUrl = new URL(`https://preview.internal:5173/contest/${CONTEST_ID}?tab=history`);
    const rendered = render(ContestPage, {
      props: {
        data: {
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
        }
      }
    });

    expect(rendered.head).toContain(`<link rel="canonical" href="https://civibus.test/contest/${CONTEST_ID}"`);
    expect(rendered.head).toContain('<meta property="og:type" content="website"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<meta name="twitter:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<script type="application/ld+json">');
    expect(rendered.head).toContain('"@graph"');
    expect(rendered.head).toContain('"@type":"Election"');
    expect(rendered.head).toContain('"@type":"BreadcrumbList"');
    expect(rendered.body).toContain('aria-label="Breadcrumb"');
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

    expect(rendered.head).toContain(
      `<link rel="canonical" href="https://civibus.test/candidacy/${CANDIDACY_ID}"`
    );
    expect(rendered.head).toContain('<meta property="og:type" content="profile"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<meta name="twitter:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<script type="application/ld+json">');
    expect(rendered.head).toContain('"@graph"');
    expect(rendered.head).toContain('"@type":"Role"');
    expect(rendered.head).toContain('"@type":"BreadcrumbList"');
    expect(rendered.body).toContain('aria-label="Breadcrumb"');
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

    expect(rendered.head).toContain(
      `<link rel="canonical" href="https://civibus.test/officeholding/${OFFICEHOLDING_ID}"`
    );
    expect(rendered.head).toContain('<meta property="og:type" content="website"');
    expect(rendered.head).toContain('<meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('<meta name="twitter:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<script type="application/ld+json">');
    expect(rendered.head).toContain('"@graph"');
    expect(rendered.head).toContain('"@type":"Role"');
    expect(rendered.head).toContain('"@type":"BreadcrumbList"');
    expect(rendered.body).toContain('aria-label="Breadcrumb"');
  });

  it("keeps /search as title-plus-description only with no canonical, OG, Twitter, or JSON-LD tags", () => {
    currentPageUrl = new URL("https://preview.internal:5173/search?q=jane");
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "jane",
          entityType: "",
          results: []
        }
      }
    });

    expect(rendered.head).toContain('<title>jane (0 results) | Search | Civibus</title>');
    expect(rendered.head).toContain(
      '<meta name="description" content="0 results for &quot;jane&quot; across Civibus records."'
    );
    expect(rendered.head).not.toContain('<link rel="canonical"');
    expect(rendered.head).not.toContain('property="og:');
    expect(rendered.head).not.toContain('name="twitter:');
    expect(rendered.head).not.toContain("application/ld+json");
    expect(rendered.body).toContain('aria-label="Browse by record type"');
    expect(rendered.body).toContain('href="/search?entity_type=person"');
    expect(rendered.body).toContain('href="/search?entity_type=org"');
    expect(rendered.body).toContain('href="/search?entity_type=committee"');
    expect(rendered.body).toContain('href="/search?entity_type=candidate"');
    expect(rendered.body).toContain('href="/search?entity_type=office"');
    expect(rendered.body).toContain(
      'placeholder="Search people, organizations, committees, candidates, or offices"'
    );
    expect(rendered.body).toContain('value="candidate"');
    expect(rendered.body).not.toContain("Candidate is intentionally excluded from this filter");
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
      expect(rendered.head).not.toContain('<link rel="canonical"');
      expect(rendered.head).not.toContain('property="og:');
      expect(rendered.head).not.toContain('name="twitter:');
      expect(rendered.head).not.toContain("application/ld+json");
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
});
