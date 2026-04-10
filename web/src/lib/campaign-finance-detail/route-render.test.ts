import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import CandidateRoutePage from "../../routes/candidate/[id]/+page.svelte";
import CommitteeRoutePage from "../../routes/committee/[id]/+page.svelte";
import DetailPage from "./DetailPage.svelte";
import {
  buildCandidateRoutePresentation,
  buildCommitteeRoutePresentation
} from "./presentation";

vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: new URL("https://civibus.test/mock-path") });
      return () => {};
    }
  }
}));

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-03-21T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";

function countOccurrences(value: string, pattern: RegExp): number {
  return (value.match(pattern) ?? []).length;
}

const CANDIDATE_CANONICAL_DATA = {
  routeKind: "canonical-detail" as const,
  detail: {
    id: CANDIDATE_ID,
    fec_candidate_id: "H0NC01001",
    name: "Pat Candidate",
    slug: "pat-candidate",
    slug_is_unique: true,
    person_id: null,
    party: "DEM",
    office: "H",
    state: "NC",
    district: "01",
    incumbent_challenge: "I",
    principal_committee_id: COMMITTEE_ID,
    sources: []
  },
  summary: {
    candidate_id: CANDIDATE_ID,
    candidate_name: "Pat Candidate",
    total_raised: "250.00",
    total_spent: "80.00",
    net: "170.00",
    transaction_count: 5,
    committees: [
      {
        committee_id: COMMITTEE_ID,
        committee_name: "Citizens for Civibus",
        slug: "citizens-for-civibus",
        slug_is_unique: true,
        total_raised: "250.00",
        total_spent: "80.00",
        net: "170.00",
        transaction_count: 5,
        jurisdiction: "federal/fec",
        data_through: "2026-03-19T00:00:00Z"
      }
    ]
  },
  ieTransactions: [],
  ieSummary: null
};

const CANDIDATE_CANONICAL_DATA_WITH_IE = {
  ...CANDIDATE_CANONICAL_DATA,
  ieTransactions: [
    {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      filing_id: null,
      committee_id: COMMITTEE_ID,
      committee_name: "Independent Expenditure Committee",
      amount: 5000,
      transaction_date: "2026-03-19",
      purpose: "Broadcast ad",
      dissemination_date: "2026-03-20",
      aggregate_amount: 5000,
      support_oppose: "S" as const
    }
  ],
  ieSummary: {
    candidate_id: CANDIDATE_ID,
    support_total: "10000.00",
    oppose_total: "2500.00",
    support_count: 2,
    oppose_count: 1,
    top_spenders: [
      {
        committee_id: COMMITTEE_ID,
        committee_name: "Independent Expenditure Committee",
        support_oppose: "S" as const,
        total_amount: "7000.00",
        transaction_count: 2
      }
    ]
  }
};

const COMMITTEE_CANONICAL_DATA = {
  routeKind: "canonical-detail" as const,
  detail: {
    id: COMMITTEE_ID,
    fec_committee_id: "C12345678",
    name: "Citizens for Civibus",
    slug: "citizens-for-civibus",
    slug_is_unique: true,
    organization_id: null,
    committee_type: "Q",
    committee_designation: "P",
    party: "DEM",
    state: "NC",
    city: "Raleigh",
    zip_code: "27601",
    treasurer_name: "Jordan Treasurer",
    sources: []
  },
  transactions: [],
  summary: {
    committee_id: COMMITTEE_ID,
    committee_name: "Citizens for Civibus",
    total_raised: "125.00",
    total_spent: "40.00",
    net: "85.00",
    transaction_count: 1,
    jurisdiction: "federal/fec",
    data_through: "2026-03-19T00:00:00Z"
  },
  filingBreakdown: {
    committee_id: COMMITTEE_ID,
    committee_name: "Citizens for Civibus",
    filings: []
  }
};

describe("campaign-finance route renders", () => {
  it("candidate +page.svelte renders canonical SEO and candidate detail content", () => {
    const rendered = render(CandidateRoutePage, {
      props: {
        data: CANDIDATE_CANONICAL_DATA
      }
    });

    expect(rendered.head).toContain("<title>Pat Candidate | Candidate | Civibus</title>");
    expect(rendered.head).toContain('meta name="description" content="Candidate profile from campaign-finance records."');
    expect(rendered.head).toContain('meta property="og:type" content="profile"');
    expect(rendered.head).toContain('link rel="canonical" href="https://civibus.test/mock-path"');
    expect(rendered.head).toContain('meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('meta name="twitter:title" content="Pat Candidate | Candidate | Civibus"');
    expect(rendered.head).toContain('meta name="twitter:description" content="Candidate profile from campaign-finance records."');
    expect(rendered.head).toContain('meta name="twitter:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<script type="application/ld+json">');
    expect(countOccurrences(rendered.head, /meta property="og:image"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /meta name="twitter:card"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /meta name="twitter:title"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /meta name="twitter:description"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /meta name="twitter:image"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /<script type="application\/ld\+json">/g)).toBe(1);
    expect(rendered.head).toContain('"@type":"Person"');
    expect(rendered.head).toContain('"name":"Pat Candidate"');
    expect(rendered.body).toContain("Candidate detail");
    expect(rendered.body).toContain("Pat Candidate");
  });

  it("candidate +page.svelte renders slug collision chooser and omits canonical SEO head tags", () => {
    const rendered = render(CandidateRoutePage, {
      props: {
        data: {
          routeKind: "slug-collision",
          slug: "pat-candidate",
          matches: [
            {
              id: CANDIDATE_ID,
              fec_candidate_id: "H0NC01001",
              name: "Pat Candidate",
              party: "DEM",
              office: "H",
              state: "NC",
              district: "01",
              slug: "pat-candidate",
              slug_is_unique: true
            },
            {
              id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
              fec_candidate_id: "H0NC01002",
              name: "Pat Candidate Jr",
              party: "DEM",
              office: "H",
              state: "NC",
              district: "02",
              slug: "pat-candidate",
              slug_is_unique: false
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain('Multiple candidates match "pat-candidate"');
    expect(rendered.body).toContain('href="/candidate/pat-candidate"');
    expect(rendered.body).toContain('href="/candidate/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"');
    expect(rendered.head).not.toContain('meta property="og:title"');
    expect(rendered.head).not.toContain('meta property="og:image"');
    expect(rendered.head).not.toContain('meta name="twitter:');
    expect(rendered.head).not.toContain('application/ld+json');
    expect(rendered.head).not.toContain('link rel="canonical"');
    expect(countOccurrences(rendered.head, /meta property="og:image"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /meta name="twitter:card"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /meta name="twitter:title"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /meta name="twitter:description"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /meta name="twitter:image"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /<script type="application\/ld\+json">/g)).toBe(0);
  });

  it("committee +page.svelte renders canonical SEO and committee detail content", () => {
    const rendered = render(CommitteeRoutePage, {
      props: {
        data: COMMITTEE_CANONICAL_DATA
      }
    });

    expect(rendered.head).toContain("<title>Citizens for Civibus | Committee | Civibus</title>");
    expect(rendered.head).toContain('meta name="description" content="Committee profile with 0 recent transactions."');
    expect(rendered.head).toContain('meta property="og:type" content="website"');
    expect(rendered.head).toContain('link rel="canonical" href="https://civibus.test/mock-path"');
    expect(rendered.head).toContain('meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('meta name="twitter:title" content="Citizens for Civibus | Committee | Civibus"');
    expect(rendered.head).toContain(
      'meta name="twitter:description" content="Committee profile with 0 recent transactions."'
    );
    expect(rendered.head).toContain('meta name="twitter:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('<script type="application/ld+json">');
    expect(countOccurrences(rendered.head, /meta property="og:image"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /meta name="twitter:card"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /meta name="twitter:title"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /meta name="twitter:description"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /meta name="twitter:image"/g)).toBe(1);
    expect(countOccurrences(rendered.head, /<script type="application\/ld\+json">/g)).toBe(1);
    expect(rendered.head).toContain('"@type":"Organization"');
    expect(rendered.head).toContain('"name":"Citizens for Civibus"');
    expect(rendered.body).toContain("Committee detail");
    expect(rendered.body).toContain("Citizens for Civibus");
  });

  it("candidate canonical detail follows the presenter section order", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation(CANDIDATE_CANONICAL_DATA)
      }
    });

    expect(rendered.body.indexOf("<h3>Core attributes</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Source and freshness</h3>")
    );
    expect(rendered.body.indexOf("<h3>Source and freshness</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Key metrics</h3>")
    );
    expect(rendered.body.indexOf("<h3>Key metrics</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Outside Spending</h3>")
    );
    expect(rendered.body.indexOf("<h3>Outside Spending</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Fundraising summary</h3>")
    );
  });

  it("committee canonical detail follows the presenter section order", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation(COMMITTEE_CANONICAL_DATA)
      }
    });

    expect(rendered.body.indexOf("<h3>Core attributes</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Source and freshness</h3>")
    );
    expect(rendered.body.indexOf("<h3>Source and freshness</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Key metrics</h3>")
    );
    expect(rendered.body.indexOf("<h3>Key metrics</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Fundraising summary</h3>")
    );
  });

  it("committee +page.svelte renders slug collision chooser and omits canonical SEO head tags", () => {
    const rendered = render(CommitteeRoutePage, {
      props: {
        data: {
          routeKind: "slug-collision",
          slug: "citizens-for-civibus",
          matches: [
            {
              id: COMMITTEE_ID,
              fec_committee_id: "C12345678",
              name: "Citizens for Civibus",
              committee_type: "Q",
              party: "DEM",
              state: "NC",
              slug: "citizens-for-civibus",
              slug_is_unique: true
            },
            {
              id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
              fec_committee_id: "C00000000",
              name: "Citizens for Civibus NC",
              committee_type: "P",
              party: "DEM",
              state: "NC",
              slug: "citizens-for-civibus",
              slug_is_unique: false
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain('Multiple committees match "citizens-for-civibus"');
    expect(rendered.body).toContain('href="/committee/citizens-for-civibus"');
    expect(rendered.body).toContain('href="/committee/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"');
    expect(rendered.head).not.toContain('meta property="og:title"');
    expect(rendered.head).not.toContain('meta property="og:image"');
    expect(rendered.head).not.toContain('meta name="twitter:');
    expect(rendered.head).not.toContain('application/ld+json');
    expect(rendered.head).not.toContain('link rel="canonical"');
    expect(countOccurrences(rendered.head, /meta property="og:image"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /meta name="twitter:card"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /meta name="twitter:title"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /meta name="twitter:description"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /meta name="twitter:image"/g)).toBe(0);
    expect(countOccurrences(rendered.head, /<script type="application\/ld\+json">/g)).toBe(0);
  });

  it("committee +page.svelte renders trust section with freshness severity, source labels, and dual-date summary", () => {
    const rendered = render(CommitteeRoutePage, {
      props: {
        data: {
          ...COMMITTEE_CANONICAL_DATA,
          detail: {
            ...COMMITTEE_CANONICAL_DATA.detail,
            sources: [
              {
                domain: "campaign_finance",
                jurisdiction: "federal/fec",
                data_source_name: "FEC",
                data_source_url: "https://www.fec.gov",
                source_record_key: "C12345678",
                record_url: "https://www.fec.gov/data/committee/C12345678/",
                pull_date: "2026-03-20T00:00:00Z"
              },
              {
                domain: "campaign_finance",
                jurisdiction: "state/NC",
                data_source_name: "NC State Board",
                data_source_url: "https://www.ncsbe.gov",
                source_record_key: "NC-COMMITTEE-001",
                record_url: null,
                pull_date: "2026-03-19T00:00:00Z"
              }
            ]
          }
        }
      }
    });

    // Freshness severity text (not color-dependent)
    expect(rendered.body).toContain("Data is current");
    // Heading
    expect(rendered.body).toContain("Source and freshness");
    // Dual-date last-pulled summary
    expect(rendered.body).toContain("1 day ago");
    expect(rendered.body).toContain("2026-03-20");
    // Human-readable source label
    expect(rendered.body).toContain("FEC (campaign_finance/federal/fec)");
    expect(rendered.body).toContain("NC State Board (campaign_finance/state/NC)");
    // Record key with redesigned label
    expect(rendered.body).toContain("Source record ID:");
    expect(rendered.body).toContain("C12345678");
    // Source link with redesigned label
    expect(rendered.body).toContain("View source record");
    expect(rendered.body).toContain('href="https://www.fec.gov/data/committee/C12345678/"');
    expect(countOccurrences(rendered.body, /View source record/g)).toBe(1);
    expect(rendered.body).toContain("Source record link unavailable.");
    // Advisory and reporting link preserved
    expect(rendered.body).toContain("Report a data issue");
  });

  it("committee +page.svelte renders honest stale trust copy when data is old", () => {
    const rendered = render(CommitteeRoutePage, {
      props: {
        data: {
          ...COMMITTEE_CANONICAL_DATA,
          detail: {
            ...COMMITTEE_CANONICAL_DATA.detail,
            sources: [
              {
                domain: "campaign_finance",
                jurisdiction: "federal/fec",
                data_source_name: "FEC",
                data_source_url: "https://www.fec.gov",
                source_record_key: "C12345678",
                record_url: null,
                pull_date: "2026-03-01T00:00:00Z"
              }
            ]
          }
        }
      }
    });

    expect(rendered.body).toContain("Data may be outdated");
  });

  it("committee +page.svelte renders empty trust section with honest no-source wording", () => {
    const rendered = render(CommitteeRoutePage, {
      props: {
        data: COMMITTEE_CANONICAL_DATA
      }
    });

    expect(rendered.body).toContain("No source records are available for this detail yet.");
    expect(rendered.body).toContain("Data freshness could not be determined");
  });
});

describe("DetailPage route presentation", () => {
  it("renders canonical detail branches from a shared route presentation contract", () => {
    const presentation = buildCandidateRoutePresentation(CANDIDATE_CANONICAL_DATA);
    const rendered = render(DetailPage, {
      props: {
        presentation
      }
    });

    expect(rendered.body).toContain("Candidate detail");
    expect(rendered.body).toContain("Pat Candidate");
  });

  it("renders readable cross-link copy instead of raw IDs or generic route labels", () => {
    const candidateRendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation({
          ...CANDIDATE_CANONICAL_DATA,
          detail: {
            ...CANDIDATE_CANONICAL_DATA.detail,
            person_id: PERSON_ID
          }
        })
      }
    });
    const committeeRendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation({
          ...COMMITTEE_CANONICAL_DATA,
          detail: {
            ...COMMITTEE_CANONICAL_DATA.detail,
            organization_id: ORG_ID
          },
          transactions: [
            {
              id: "55555555-5555-4555-8555-555555555555",
              filing_id: "66666666-6666-4666-8666-666666666666",
              committee_id: COMMITTEE_ID,
              transaction_type: "contribution",
              transaction_identifier: "TX-1",
              transaction_date: "2026-03-19",
              amount: 125,
              contributor_name_raw: "Donor One",
              contributor_employer: null,
              contributor_occupation: null,
              contributor_city: null,
              contributor_state: null,
              contributor_zip: null,
              contributor_person_id: PERSON_ID,
              contributor_organization_id: ORG_ID,
              contributor_address_id: null,
              recipient_candidate_id: CANDIDATE_ID,
              recipient_committee_id: COMMITTEE_ID,
              memo_text: null,
              is_memo: false,
              amendment_indicator: "N",
              date_is_reliable: true
            }
          ]
        })
      }
    });

    expect(candidateRendered.body).toContain(`Person record (${PERSON_ID})`);
    expect(candidateRendered.body).toContain(`Committee record (${COMMITTEE_ID})`);
    expect(committeeRendered.body).toContain(`Organization record (${ORG_ID})`);
    expect(committeeRendered.body).toContain("View contributor person record");
    expect(committeeRendered.body).toContain("View contributor organization record");
    expect(committeeRendered.body).toContain("View recipient candidate record");
    expect(committeeRendered.body).toContain("View recipient committee record");
  });

  it("renders slug collision chooser from the shared route presentation contract", () => {
    const presentation = buildCommitteeRoutePresentation({
      routeKind: "slug-collision",
      slug: "citizens-for-civibus",
      matches: [
        {
          id: COMMITTEE_ID,
          fec_committee_id: "C12345678",
          name: "Citizens for Civibus",
          committee_type: "Q",
          party: "DEM",
          state: "NC",
          slug: "citizens-for-civibus",
          slug_is_unique: true
        }
      ]
    });
    const rendered = render(DetailPage, {
      props: {
        presentation
      }
    });

    expect(rendered.body).toContain('Multiple committees match "citizens-for-civibus"');
    expect(rendered.body).toContain('aria-label="Select a committee record"');
    expect(rendered.body).toContain('href="/committee/citizens-for-civibus"');
  });

  it("renders outside-spending analysis groups with committee links and dissemination dates", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation(CANDIDATE_CANONICAL_DATA_WITH_IE)
      }
    });

    expect(rendered.body).toContain(
      "Outside spending is independent and not controlled by the candidate committee."
    );
    expect(rendered.body).toContain("Support spending");
    expect(rendered.body).toContain("Oppose spending");
    expect(rendered.body).toContain("$10,000.00");
    expect(rendered.body).toContain("$2,500.00");
    expect(rendered.body).toContain("2 expenditures");
    expect(rendered.body).toContain("1 expenditure");
    expect(rendered.body).toContain('href="/committee/33333333-3333-4333-8333-333333333333"');
    expect(rendered.body).toContain("dissemination date: 2026-03-20");
  });

  it("renders revised outside-spending empty-state copy for missing and zero-value summaries", () => {
    const missingSummaryRendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation(CANDIDATE_CANONICAL_DATA)
      }
    });
    const zeroSummaryRendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation({
          ...CANDIDATE_CANONICAL_DATA,
          ieSummary: {
            candidate_id: CANDIDATE_ID,
            support_total: "0.00",
            oppose_total: "0.00",
            support_count: 0,
            oppose_count: 0,
            top_spenders: []
          },
          ieTransactions: []
        })
      }
    });

    expect(missingSummaryRendered.body).toContain(
      "Outside-spending data is not yet available for this candidate. Coverage may be incomplete."
    );
    expect(zeroSummaryRendered.body).toContain(
      "No outside spending is reported in available filings. Coverage may be incomplete."
    );
  });
});

describe("breadcrumb parity on campaign-finance detail routes", () => {
  it("candidate canonical detail renders breadcrumb UI and breadcrumb JSON-LD from the same crumbs", () => {
    const rendered = render(CandidateRoutePage, {
      props: {
        data: CANDIDATE_CANONICAL_DATA
      }
    });

    expect(rendered.body).toContain('aria-label="Breadcrumb"');
    expect(rendered.body).toContain('href="/"');
    expect(rendered.body).toContain("Pat Candidate");
    expect(rendered.head).toContain('"BreadcrumbList"');
    expect(rendered.head).toContain('"Home"');
  });

  it("committee canonical detail renders breadcrumb UI and breadcrumb JSON-LD from the same crumbs", () => {
    const rendered = render(CommitteeRoutePage, {
      props: {
        data: COMMITTEE_CANONICAL_DATA
      }
    });

    expect(rendered.body).toContain('aria-label="Breadcrumb"');
    expect(rendered.body).toContain('href="/"');
    expect(rendered.body).toContain("Citizens for Civibus");
    expect(rendered.head).toContain('"BreadcrumbList"');
    expect(rendered.head).toContain('"Home"');
  });

  it("candidate slug collision omits breadcrumb JSON-LD but still renders breadcrumb UI", () => {
    const rendered = render(CandidateRoutePage, {
      props: {
        data: {
          routeKind: "slug-collision",
          slug: "pat-candidate",
          matches: [
            {
              id: CANDIDATE_ID,
              fec_candidate_id: "H0NC01001",
              name: "Pat Candidate",
              party: "DEM",
              office: "H",
              state: "NC",
              district: "01",
              slug: "pat-candidate",
              slug_is_unique: true
            }
          ]
        }
      }
    });

    expect(rendered.head).not.toContain('"BreadcrumbList"');
  });
});
