import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import { readFileSync } from "node:fs";
import CandidateRoutePage from "../../routes/candidate/[id]/+page.svelte";
import CommitteeRoutePage from "../../routes/committee/[id]/+page.svelte";
import { PHL_FRESHNESS_NOTE } from "$lib/detail-trust/presentation";
import DetailPage from "./DetailPage.svelte";
import {
  buildCandidateRoutePresentation,
  buildCommitteeRoutePresentation
} from "./presentation";
import { COMMITTEE_FILINGS_WINDOW_LIMIT } from "./contract";
import {
  CANDIDATE_CANONICAL_DATA,
  CANDIDATE_CANONICAL_DATA_WITH_L10_DEVIATION,
  CANDIDATE_CANONICAL_DATA_WITH_IE,
  CANDIDATE_EMPTY_CANONICAL_DATA,
  CANDIDATE_ID,
  COMMITTEE_CANONICAL_DATA,
  COMMITTEE_CANONICAL_DATA_WITH_PAGINATED_FILINGS,
  COMMITTEE_CANONICAL_DATA_WITH_IE,
  COMMITTEE_ID,
  DEFAULT_SELECTED_CYCLE_FIELDS,
  ORG_ID,
  PERSON_ID,
  SAMPLE_TRANSACTION,
  asDeferredValue
} from "./route-render.test-fixtures";

vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

const mockPageStore = vi.hoisted(() => ({
  url: new URL("https://civibus.test/mock-path")
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: mockPageStore.url });
      return () => {};
    }
  }
}));

function setMockPageUrl(pathAndSearch: string): void {
  mockPageStore.url = new URL(pathAndSearch, "https://civibus.test");
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-03-21T12:00:00Z"));
  setMockPageUrl("/mock-path");
});

afterEach(() => {
  vi.useRealTimers();
});

function countOccurrences(value: string, pattern: RegExp): number {
  return (value.match(pattern) ?? []).length;
}

function extractElementByTestId(html: string, testId: string): string | null {
  const marker = `data-testid="${testId}"`;
  const markerIndex = html.indexOf(marker);

  if (markerIndex === -1) {
    return null;
  }

  const openStartIndex = html.lastIndexOf("<", markerIndex);
  if (openStartIndex === -1) {
    return null;
  }

  const openEndIndex = html.indexOf(">", markerIndex);
  if (openEndIndex === -1) {
    return null;
  }

  const tagNameMatch = html.slice(openStartIndex, openEndIndex + 1).match(/^<([a-z0-9-]+)/i);
  if (!tagNameMatch) {
    return null;
  }

  const tagName = tagNameMatch[1];
  const sameTagPattern = new RegExp(`<\\/?${tagName}(?:\\s[^>]*)?>`, "gi");
  let depth = 1;
  sameTagPattern.lastIndex = openEndIndex + 1;

  while (depth > 0) {
    const match = sameTagPattern.exec(html);
    if (!match) {
      return null;
    }

    const token = match[0];
    const isClosingTag = token.startsWith("</");
    const isSelfClosingTag = token.endsWith("/>");

    if (isClosingTag) {
      depth -= 1;
    } else if (!isSelfClosingTag) {
      depth += 1;
    }

    if (depth === 0) {
      return html.slice(openStartIndex, match.index + token.length);
    }
  }

  return null;
}

function extractFilingTable(html: string): string {
  const filingTable = extractElementByTestId(html, "filing-breakdown-scroll");
  expect(filingTable).not.toBeNull();
  return filingTable!;
}

function extractFilingTableRowIdentities(html: string): string[] {
  return Array.from(html.matchAll(/<td>Filing (\d{3}) \(FEC-\1\)<\/td>/g), ([, sequence]) => {
    return `filing-${sequence}`;
  });
}

function extractHrefByTestId(html: string, testId: string): string {
  const anchor = extractElementByTestId(html, testId);
  expect(anchor).not.toBeNull();
  const href = anchor!.match(/\shref="([^"]+)"/)?.[1];
  expect(href).toBeDefined();
  return href!.replaceAll("&amp;", "&");
}

describe("extractElementByTestId", () => {
  it("extracts the full wrapper when the wrapper contains nested elements of the same tag", () => {
    const html =
      '<section><div data-testid="wrapper"><div class="inner"><div>value</div></div></div></section>';

    expect(extractElementByTestId(html, "wrapper")).toBe(
      '<div data-testid="wrapper"><div class="inner"><div>value</div></div></div>'
    );
  });
});

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
    expect(rendered.head).toContain('meta name="description" content="Committee profile from campaign-finance records."');
    expect(rendered.head).toContain('meta property="og:type" content="website"');
    expect(rendered.head).toContain('link rel="canonical" href="https://civibus.test/mock-path"');
    expect(rendered.head).toContain('meta property="og:image" content="https://civibus.test/og-default.png"');
    expect(rendered.head).toContain('meta name="twitter:card" content="summary_large_image"');
    expect(rendered.head).toContain('meta name="twitter:title" content="Citizens for Civibus | Committee | Civibus"');
    expect(rendered.head).toContain(
      'meta name="twitter:description" content="Committee profile from campaign-finance records."'
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

  it("keeps the frontend filing window limit aligned with the backend SSOT", () => {
    const backendConstants = readFileSync(
      new URL("../../../../domains/campaign_finance/constants.py", import.meta.url),
      "utf8"
    );
    const backendWindowLimit = backendConstants.match(/^FILING_BREAKDOWN_STORE_LIMIT = (\d+)$/m);

    expect(backendWindowLimit).not.toBeNull();
    expect(COMMITTEE_FILINGS_WINDOW_LIMIT).toBe(Number(backendWindowLimit![1]));
    expect(COMMITTEE_FILINGS_WINDOW_LIMIT).toBe(200);
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
      rendered.body.indexOf("<h3>Outside Spending</h3>")
    );
    expect(rendered.body.indexOf("<h3>Outside Spending</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Fundraising summary</h3>")
    );
    expect(rendered.body.indexOf("<h3>Fundraising summary</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Receipt split</h3>")
    );
    expect(rendered.body.indexOf("<h3>Receipt split</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Top donors</h3>")
    );
    expect(rendered.body.indexOf("<h3>Top donors</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Top vendors</h3>")
    );
    expect(rendered.body.indexOf("<h3>Top vendors</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Per-cycle history</h3>")
    );
    expect(rendered.body.indexOf("<h3>Per-cycle history</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Cash-on-hand trend</h3>")
    );
    expect(rendered.body.indexOf("<h3>Cash-on-hand trend</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Filing-period breakdown</h3>")
    );
    expect(rendered.body.indexOf("<h3>Filing-period breakdown</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Recent transactions</h3>")
    );
  });

  it("renders committee outside-spending empty state from the committee IE payload", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation(COMMITTEE_CANONICAL_DATA)
      }
    });

    const wrapper = extractElementByTestId(rendered.body, "committee-outside-spending");
    expect(wrapper).not.toBeNull();
    expect(wrapper).toContain("<h3>Outside Spending</h3>");
    expect(wrapper).toContain("This committee reported no independent expenditures");
  });

  it("renders committee outside-spending outlier note when filtering leaves no displayed activity", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation({
          ...COMMITTEE_CANONICAL_DATA,
          independentExpendituresMade: asDeferredValue({
            committee_id: COMMITTEE_ID,
            support_total: "0.00",
            oppose_total: "0.00",
            ie_transaction_count: 0,
            excluded_outlier_count: 2,
            targets: []
          })
        })
      }
    });

    const wrapper = extractElementByTestId(rendered.body, "committee-outside-spending");
    expect(wrapper).not.toBeNull();
    expect(wrapper).toContain("This committee reported no independent expenditures");
    expect(wrapper).toContain(
      "2 reported independent expenditures were excluded from these totals as outliers."
    );
  });

  it("renders committee outside-spending totals, ordered targets, and source links", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation(COMMITTEE_CANONICAL_DATA_WITH_IE)
      }
    });

    const wrapper = extractElementByTestId(rendered.body, "committee-outside-spending");
    const targets = extractElementByTestId(rendered.body, "committee-outside-spending-targets");
    const sources = extractElementByTestId(rendered.body, "committee-outside-spending-sources");
    expect(wrapper).not.toBeNull();
    expect(targets).not.toBeNull();
    expect(sources).not.toBeNull();
    expect(wrapper).toContain("$1,700.00");
    expect(wrapper).toContain("$250.00");
    expect(wrapper).toContain("4 expenditures");
    expect(wrapper).toContain(
      "1 reported independent expenditure was excluded from these totals as an outlier."
    );
    expect(targets).toContain('href="/person/11111111-1111-4111-8111-111111111111"');
    expect(targets).toContain("Pat Candidate");
    expect(targets).toContain("Lower Target");
    expect(targets!.indexOf("Pat Candidate")).toBeLessThan(targets!.indexOf("Lower Target"));
    expect(sources).toContain('href="https://www.fec.gov/data/independent-expenditures/"');
    expect(sources).toContain("schedule-e-source");
  });

  it("renders committee high-signal receipts and expenditure panels", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation({
          ...COMMITTEE_CANONICAL_DATA,
          summary: asDeferredValue({
            ...(COMMITTEE_CANONICAL_DATA.summary as unknown as Awaited<typeof COMMITTEE_CANONICAL_DATA.summary>),
            top_donors: [{ name: "Donor One", total_amount: "80.00", transaction_count: 2 }],
            top_vendors: [{ name: "Vendor One", total_amount: "40.00", transaction_count: 1 }],
            spend_categories: [{ category: "media", total_amount: "25.00", transaction_count: 1 }]
          }),
          filingBreakdown: asDeferredValue({
            ...(COMMITTEE_CANONICAL_DATA.filingBreakdown as unknown as Awaited<typeof COMMITTEE_CANONICAL_DATA.filingBreakdown>),
            filings: [
              {
                filing_id: "f1",
                filing_fec_id: "FEC-1",
                filing_name: "Q1",
                report_type: "Q1",
                amendment_indicator: "N",
                coverage_start_date: "2026-01-01",
                coverage_end_date: "2026-03-31",
                receipt_date: "2026-04-10",
                total_raised: "125.00",
                total_spent: "40.00",
                net: "85.00",
                transaction_count: 1,
                cash_on_hand: "85.00",
                row_id: "f1:N"
              },
              {
                filing_id: "f2",
                filing_fec_id: "FEC-2",
                filing_name: "Q2",
                report_type: "Q2",
                amendment_indicator: "N",
                coverage_start_date: "2026-05-01",
                coverage_end_date: "2026-06-30",
                receipt_date: "2026-07-15",
                total_raised: "250.00",
                total_spent: "84.50",
                net: "165.50",
                transaction_count: 2,
                cash_on_hand: "250.50",
                row_id: "f2:N"
              }
            ]
          })
        })
      }
    });

    expect(rendered.body).toContain("<h3>Receipt split</h3>");
    expect(rendered.body).toContain("Cash receipts");
    expect(rendered.body).toContain("In-kind receipts");
    expect(rendered.body).toContain("Loans");
    expect(rendered.body).toContain("Contributions");
    expect(rendered.body).toContain("<h3>Top donors</h3>");
    expect(rendered.body).toContain("Donor One");
    expect(rendered.body).toContain("<h3>Top vendors</h3>");
    expect(rendered.body).toContain("Vendor One");
    expect(rendered.body).toContain("<h3>Spend categories</h3>");
    expect(rendered.body).toContain("media");
    expect(rendered.body).toContain("<h3>Cash-on-hand trend</h3>");
    expect(rendered.body).toContain(
      "Cash on hand is $250.50 at the latest filing period in the 2026 cycle."
    );
    expect(rendered.body).toContain("March 31, 2026");
    expect(rendered.body).toContain("June 30, 2026");
    expect(rendered.body).toContain("Missing source coverage before this filing period.");
    expect(rendered.body).toContain("View chart data");
    expect(rendered.body).toContain('aria-label="Cash on hand trend by filing period"');
    expect(rendered.body).not.toContain('aria-label="Committee cash-on-hand trend"');

    const filingTable = extractElementByTestId(rendered.body, "filing-breakdown-scroll");
    expect(filingTable).not.toBeNull();
    expect(filingTable).toContain("<th>Total receipts</th>");
    expect(filingTable).toContain("<th>Total disbursements</th>");
    expect(filingTable).toContain("<th>Cash on hand</th>");
    expect(filingTable).toContain("<th>Transactions</th>");
    expect(filingTable).not.toContain("<th>Raised</th>");
    expect(filingTable).not.toContain("<th>Spent</th>");
    expect(filingTable).not.toContain("<th>Net</th>");
  });

  it("renders the first filing table page from the fetched recent window", () => {
    setMockPageUrl("/committee/citizens-for-civibus");
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation(COMMITTEE_CANONICAL_DATA_WITH_PAGINATED_FILINGS)
      }
    });

    const filingTable = extractFilingTable(rendered.body);
    const rowIdentities = extractFilingTableRowIdentities(filingTable);

    expect(rowIdentities).toHaveLength(25);
    expect(rowIdentities[0]).toBe("filing-060");
    expect(rowIdentities[24]).toBe("filing-036");
    expect(extractElementByTestId(rendered.body, "filing-breakdown-pagination-label")).toContain(
      "Showing 1–25 of 60 most recent · 220,706 total filings"
    );
    expect(extractElementByTestId(rendered.body, "filing-breakdown-next")).not.toBeNull();
    expect(extractElementByTestId(rendered.body, "filing-breakdown-prev")).toBeNull();
    expect(extractElementByTestId(rendered.body, "committee-cash-on-hand-trend")).not.toBeNull();
  });

  it("renders the second filing table page from filings_offset", () => {
    setMockPageUrl("/committee/citizens-for-civibus?filings_offset=25");
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation(COMMITTEE_CANONICAL_DATA_WITH_PAGINATED_FILINGS)
      }
    });

    const rowIdentities = extractFilingTableRowIdentities(extractFilingTable(rendered.body));

    expect(rowIdentities).toEqual([
      "filing-035",
      "filing-034",
      "filing-033",
      "filing-032",
      "filing-031",
      "filing-030",
      "filing-029",
      "filing-028",
      "filing-027",
      "filing-026",
      "filing-025",
      "filing-024",
      "filing-023",
      "filing-022",
      "filing-021",
      "filing-020",
      "filing-019",
      "filing-018",
      "filing-017",
      "filing-016",
      "filing-015",
      "filing-014",
      "filing-013",
      "filing-012",
      "filing-011"
    ]);
    expect(extractElementByTestId(rendered.body, "filing-breakdown-pagination-label")).toContain(
      "Showing 26–50 of 60 most recent · 220,706 total filings"
    );
    expect(extractElementByTestId(rendered.body, "filing-breakdown-prev")).not.toBeNull();
    expect(extractElementByTestId(rendered.body, "filing-breakdown-next")).not.toBeNull();
  });

  it("preserves unrelated query parameters while building normalized filing page hrefs", () => {
    setMockPageUrl("/committee/citizens-for-civibus?cycle=2026&filings_offset=26&view=records");
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation(COMMITTEE_CANONICAL_DATA_WITH_PAGINATED_FILINGS)
      }
    });

    expect(extractHrefByTestId(rendered.body, "filing-breakdown-prev")).toBe(
      "/committee/citizens-for-civibus?cycle=2026&view=records&filings_offset=0"
    );
    expect(extractHrefByTestId(rendered.body, "filing-breakdown-next")).toBe(
      "/committee/citizens-for-civibus?cycle=2026&view=records&filings_offset=50"
    );
  });

  it("renders explicit no-category and no-trend messages when committee summary omits those aggregates", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation({
          ...COMMITTEE_CANONICAL_DATA,
          summary: asDeferredValue({
            ...(COMMITTEE_CANONICAL_DATA.summary as unknown as Awaited<typeof COMMITTEE_CANONICAL_DATA.summary>),
            spend_categories: null
          }),
          filingBreakdown: asDeferredValue({
            ...(COMMITTEE_CANONICAL_DATA.filingBreakdown as unknown as Awaited<typeof COMMITTEE_CANONICAL_DATA.filingBreakdown>),
            filings: []
          })
        })
      }
    });

    expect(rendered.body).toContain("Spend categories are not available for this committee.");
    expect(rendered.body).toContain("Cash on hand needs two or more dated filing-period values before plotting.");
    expect(rendered.body).not.toContain('aria-label="Committee cash-on-hand trend"');
  });

  it("renders IE-aware committee transaction columns via presenter-normalized fields", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation({
          ...COMMITTEE_CANONICAL_DATA,
          transactions: asDeferredValue([
            {
              ...SAMPLE_TRANSACTION,
              support_oppose: "S" as const,
              dissemination_date: "2026-03-20",
              aggregate_amount: 300
            }
          ])
        })
      }
    });

    expect(rendered.body).toContain("<th>Stance</th>");
    expect(rendered.body).toContain("<th>Dissemination Date</th>");
    expect(rendered.body).toContain("<th>Aggregate Amount</th>");
    expect(rendered.body).toContain("<td>Support</td>");
    expect(rendered.body).toContain("<td>2026-03-20</td>");
    expect(rendered.body).toContain("<td>$300.00</td>");
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
                data_source_url: "not-a-valid-url",
                source_record_key: "NC-COMMITTEE-001",
                record_url: null,
                pull_date: "2026-03-19T00:00:00Z"
              },
              {
                domain: "campaign_finance",
                jurisdiction: "municipality/PHL",
                data_source_name: "Philadelphia Board of Elections",
                data_source_url: "https://www.phila.gov",
                source_record_key: "PHL-COMMITTEE-001",
                record_url: null,
                pull_date: "2026-03-18T00:00:00Z"
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
    expect(countOccurrences(rendered.body, /View source record/g)).toBe(2);
    expect(rendered.body).toContain("Source record link unavailable.");
    // Advisory and reporting link preserved
    expect(rendered.body).toContain("Report a data issue");
    expect(rendered.body).toContain(PHL_FRESHNESS_NOTE);
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

  it("candidate and committee routes keep unknown-freshness fallback when source dates are malformed", () => {
    const malformedSource = {
      domain: "campaign_finance",
      jurisdiction: "state/NC",
      data_source_name: "NC State Board",
      data_source_url: "https://www.ncsbe.gov",
      source_record_key: "bad-date-source",
      record_url: null,
      pull_date: "not-a-date"
    };

    const candidateRendered = render(CandidateRoutePage, {
      props: {
        data: {
          ...CANDIDATE_CANONICAL_DATA,
          detail: {
            ...CANDIDATE_CANONICAL_DATA.detail,
            sources: [malformedSource]
          }
        }
      }
    });
    const committeeRendered = render(CommitteeRoutePage, {
      props: {
        data: {
          ...COMMITTEE_CANONICAL_DATA,
          detail: {
            ...COMMITTEE_CANONICAL_DATA.detail,
            sources: [malformedSource]
          }
        }
      }
    });

    for (const rendered of [candidateRendered, committeeRendered]) {
      expect(rendered.body).toContain("Data freshness could not be determined");
      expect(rendered.body).not.toContain("No source records are available for this detail yet.");
    }
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
          transactions: asDeferredValue([SAMPLE_TRANSACTION])
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

  it("renders committee transactions inside a scoped semantic table with cross-links", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation({
          ...COMMITTEE_CANONICAL_DATA,
          transactions: asDeferredValue([SAMPLE_TRANSACTION])
        })
      }
    });

    const wrapper = extractElementByTestId(rendered.body, "committee-transactions-scroll");
    expect(wrapper).not.toBeNull();
    expect(wrapper).toContain('class="detail__table-scroll"');
    expect(wrapper).toContain("<table>");
    expect(wrapper).toContain("<thead>");
    expect(wrapper).toContain("<th>Date</th>");
    expect(wrapper).toContain("<th>Amount</th>");
    expect(wrapper).toContain("<th>Type</th>");
    expect(wrapper).toContain("<th>Contributor</th>");
    expect(wrapper).toContain("<th>Recipient</th>");
    expect(wrapper).toContain(`href="/person/${PERSON_ID}"`);
    expect(wrapper).toContain(`href="/org/${ORG_ID}"`);
    expect(wrapper).toContain(`href="/candidate/${CANDIDATE_ID}"`);
    expect(wrapper).toContain(`href="/committee/${COMMITTEE_CANONICAL_DATA.detail.slug}"`);
  });

  it("renders top spenders inside a scoped semantic table", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation(CANDIDATE_CANONICAL_DATA_WITH_IE)
      }
    });

    const wrapper = extractElementByTestId(rendered.body, "top-spenders-scroll");
    expect(wrapper).not.toBeNull();
    expect(wrapper).toContain('class="detail__table-scroll"');
    expect(wrapper).toContain("<table>");
    expect(wrapper).toContain("<thead>");
    expect(wrapper).toContain("<th>Committee</th>");
    expect(wrapper).toContain("<th>Stance</th>");
    expect(wrapper).toContain("<th>Total</th>");
    expect(wrapper).toContain("<th>Transactions</th>");
    expect(wrapper).toContain(`href="/committee/${COMMITTEE_ID}"`);
    expect(wrapper).toContain("Support");
    expect(wrapper).toContain("$7,000.00");
  });

  it("renders outside-spending transactions inside a scoped semantic table", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation(CANDIDATE_CANONICAL_DATA_WITH_IE)
      }
    });

    const wrapper = extractElementByTestId(rendered.body, "outside-spending-transactions-scroll");
    expect(wrapper).not.toBeNull();
    expect(wrapper).toContain('class="detail__table-scroll"');
    expect(wrapper).toContain("<table>");
    expect(wrapper).toContain("<thead>");
    expect(wrapper).toContain("<th>Date</th>");
    expect(wrapper).toContain("<th>Spender</th>");
    expect(wrapper).toContain("<th>Stance</th>");
    expect(wrapper).toContain("<th>Amount</th>");
    expect(wrapper).toContain("<th>Dissemination Date</th>");
    expect(wrapper).toContain(`href="/committee/${COMMITTEE_ID}"`);
    expect(wrapper).toContain("<td>2026-03-20</td>");
    expect(wrapper).not.toContain("dissemination date: 2026-03-20");
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
    expect(rendered.body).toContain("<td>2026-03-20</td>");
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
          ieSummary: asDeferredValue({
            ...DEFAULT_SELECTED_CYCLE_FIELDS,
            candidate_id: CANDIDATE_ID,
            support_total: "0.00",
            oppose_total: "0.00",
            support_count: 0,
            oppose_count: 0,
            top_spenders: [],
            excluded_outlier_count: 0
          }),
          ieTransactions: asDeferredValue([])
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

  it("renders L10 coverage warnings before key metrics when a candidate warning exists", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation(CANDIDATE_CANONICAL_DATA_WITH_L10_DEVIATION)
      }
    });

    expect(rendered.body.indexOf("<h3>Source and freshness</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Data coverage warning</h3>")
    );
    expect(rendered.body.indexOf("<h3>Data coverage warning</h3>")).toBeLessThan(
      rendered.body.indexOf("<h3>Key metrics</h3>")
    );
  });

  it("renders an L10 caveat banner when a candidate detail page has zero loaded fundraising", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation(CANDIDATE_EMPTY_CANONICAL_DATA)
      }
    });

    expect(rendered.body).toMatch(
      /<section(?=[^>]*class="detail__panel caveat-banner")(?=[^>]*role="note")(?=[^>]*aria-label="Data coverage warning")[^>]*>/
    );
    expect(rendered.body).toContain("<h3>Data coverage warning</h3>");
    expect(rendered.body).toContain(
      "No transactions loaded for this candidate yet. Coverage may be incomplete."
    );
    expect(rendered.body).toContain('href="/methodology"');
  });

  it("renders an L10 caveat banner when a candidate total deviates from the anchor reference", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation(CANDIDATE_CANONICAL_DATA_WITH_L10_DEVIATION)
      }
    });

    expect(rendered.body).toContain("<h3>Data coverage warning</h3>");
    expect(rendered.body).toContain(
      "Civibus shows $250.00 raised, but the NC SBOE anchor reference is $1,000.00. Coverage may be incomplete."
    );
    expect(rendered.body).toContain('href="/methodology"');
  });
});

describe("campaign-finance detail key metrics section", () => {
  it("committee canonical detail renders key metrics inside a scoped metrics hook distinct from fundraising summary", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation(COMMITTEE_CANONICAL_DATA)
      }
    });

    const metricsWrapper = extractElementByTestId(rendered.body, "key-metrics");
    expect(metricsWrapper).not.toBeNull();
    expect(metricsWrapper).toContain("<h3>Key metrics</h3>");
    expect(metricsWrapper).toContain("Total raised");
    expect(metricsWrapper).toContain("$125.00");
    expect(metricsWrapper).toContain("Total spent");
    expect(metricsWrapper).toContain("$40.00");
    expect(metricsWrapper).toContain("Itemized transactions loaded");
    expect(metricsWrapper).toContain(">1<");
    // Metrics wrapper must not pull in Fundraising-summary-only fields.
    expect(metricsWrapper).not.toContain("Jurisdiction");
    expect(metricsWrapper).not.toContain("Data through");
    expect(metricsWrapper).not.toContain("Fundraising summary");
    // Key metrics must appear before the Fundraising summary section so it reads as a primary scan target.
    const metricsIndex = rendered.body.indexOf('data-testid="key-metrics"');
    const fundraisingIndex = rendered.body.indexOf('aria-label="Fundraising summary"');
    expect(metricsIndex).toBeGreaterThan(-1);
    expect(fundraisingIndex).toBeGreaterThan(-1);
    expect(metricsIndex).toBeLessThan(fundraisingIndex);
    // Hook must appear exactly once per page.
    expect(countOccurrences(rendered.body, /data-testid="key-metrics"/g)).toBe(1);
  });

  it("candidate canonical detail renders key metrics inside a scoped metrics hook distinct from fundraising summary", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCandidateRoutePresentation(CANDIDATE_CANONICAL_DATA)
      }
    });

    const metricsWrapper = extractElementByTestId(rendered.body, "key-metrics");
    expect(metricsWrapper).not.toBeNull();
    expect(metricsWrapper).toContain("<h3>Key metrics</h3>");
    expect(metricsWrapper).toContain("Total raised");
    expect(metricsWrapper).toContain("$250.00");
    expect(metricsWrapper).toContain("Total spent");
    expect(metricsWrapper).toContain("$80.00");
    expect(metricsWrapper).toContain("Itemized transactions loaded");
    expect(metricsWrapper).toContain(">5<");
    // Metrics wrapper must not pull in Fundraising-summary-only fields.
    expect(metricsWrapper).not.toContain("Fundraising summary");
    expect(metricsWrapper).not.toContain("Committee breakdown");
    // Key metrics must appear before the Fundraising summary section so it reads as a primary scan target.
    const metricsIndex = rendered.body.indexOf('data-testid="key-metrics"');
    const fundraisingIndex = rendered.body.indexOf('aria-label="Fundraising summary"');
    expect(metricsIndex).toBeGreaterThan(-1);
    expect(fundraisingIndex).toBeGreaterThan(-1);
    expect(metricsIndex).toBeLessThan(fundraisingIndex);
    // Hook must appear exactly once per page.
    expect(countOccurrences(rendered.body, /data-testid="key-metrics"/g)).toBe(1);
  });

  it("enforces key-metrics card radius and label tracking guardrails in shared detail styles", () => {
    const appCss = readFileSync(new URL("../../app.css", import.meta.url), "utf8");
    const metricRule = appCss.match(/\.detail__metric\s*\{([^}]*)\}/);
    const metricLabelRule = appCss.match(/\.detail__metric-label\s*\{([^}]*)\}/);

    expect(metricRule?.[1]).toBeDefined();
    expect(metricRule?.[1]).toMatch(/border-radius:\s*(?:8px|0\.5rem)\s*;/);
    expect(metricLabelRule?.[1]).toBeDefined();
    expect(metricLabelRule?.[1]).toMatch(/letter-spacing:\s*0(?:px|rem|em)?\s*;/);
  });
});

describe("committee detail truthfulness (Stage 6)", () => {
  it("renders positive official FEC totals in key metrics even when itemized transactions are zero", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation({
          ...COMMITTEE_CANONICAL_DATA,
          summary: asDeferredValue({
            ...(COMMITTEE_CANONICAL_DATA.summary as unknown as Awaited<
              typeof COMMITTEE_CANONICAL_DATA.summary
            >),
            total_raised: "1000000.00",
            total_spent: "500000.00",
            net: "500000.00",
            transaction_count: 0,
            itemized_transaction_count: 0,
            summary_source: "fec_committee_summary"
          })
        })
      }
    });

    const metricsWrapper = extractElementByTestId(rendered.body, "key-metrics");
    expect(metricsWrapper).not.toBeNull();
    expect(metricsWrapper).toContain("$1,000,000.00");
    expect(metricsWrapper).toContain("$500,000.00");
    // Ensure the false-$0 collapse never fires when official totals exist.
    expect(metricsWrapper).not.toMatch(/Total raised[\s\S]{0,80}\$0\.00/);
    expect(rendered.body).toContain("Official FEC committee summary");
    expect(rendered.body).toContain(
      "Itemized transactions loaded: 0. Official totals above come directly from the FEC committee summary and are not derived from these transactions."
    );
  });

  it("renders a per-cycle history table sourced from cycle_summaries", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation({
          ...COMMITTEE_CANONICAL_DATA,
          summary: asDeferredValue({
            ...(COMMITTEE_CANONICAL_DATA.summary as unknown as Awaited<
              typeof COMMITTEE_CANONICAL_DATA.summary
            >),
            cycle_summaries: [
              {
                cycle: 2026,
                total_receipts: "500000.00",
                total_disbursements: "250000.00",
                cash_on_hand: "250000.00",
                coverage_start_date: "2025-01-01",
                coverage_end_date: "2026-06-30"
              },
              {
                cycle: 2024,
                total_receipts: "800000.00",
                total_disbursements: "780000.00",
                cash_on_hand: "20000.00",
                coverage_start_date: "2023-01-01",
                coverage_end_date: "2024-12-31"
              }
            ]
          })
        })
      }
    });

    const wrapper = extractElementByTestId(rendered.body, "committee-cycle-summaries-scroll");
    expect(wrapper).not.toBeNull();
    expect(rendered.body).toContain("<h3>Per-cycle history</h3>");
    expect(wrapper).toContain("<th>Cycle</th>");
    expect(wrapper).toContain("<th>Coverage</th>");
    expect(wrapper).toContain("<th>Total receipts</th>");
    expect(wrapper).toContain("<th>Total disbursements</th>");
    expect(wrapper).toContain("<th>Cash on hand</th>");
    expect(wrapper).toContain("<td>2026</td>");
    expect(wrapper).toContain("<td>2025-01-01 to 2026-06-30</td>");
    expect(wrapper).toContain("<td>$500,000.00</td>");
    expect(wrapper).toContain("<td>2024</td>");
    expect(wrapper).toContain("<td>$800,000.00</td>");
  });

  it("renders linked candidates from the committee detail shell as slug-aware links", () => {
    const rendered = render(DetailPage, {
      props: {
        presentation: buildCommitteeRoutePresentation({
          ...COMMITTEE_CANONICAL_DATA,
          detail: {
            ...COMMITTEE_CANONICAL_DATA.detail,
            linked_candidates: [
              {
                id: CANDIDATE_ID,
                fec_candidate_id: "H0LA04001",
                name: "Mike Johnson",
                party: "REP",
                office: "H",
                state: "LA",
                district: "04",
                slug: "mike-johnson",
                slug_is_unique: true
              }
            ]
          }
        })
      }
    });

    const wrapper = extractElementByTestId(rendered.body, "committee-linked-candidates");
    expect(wrapper).not.toBeNull();
    expect(wrapper).toContain('href="/candidate/mike-johnson"');
    expect(wrapper).toContain("Mike Johnson");
    expect(wrapper).toContain("H · LA · District 04 · REP");
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
