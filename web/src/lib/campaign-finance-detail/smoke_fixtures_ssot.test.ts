import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  buildCongressSmokeSeedSql,
  discoverLiveLouisianaCommitteeRoute,
  getSeededStage6CommitteeRoute,
  SMOKE_PERSON_SMALL_DOLLAR_HEADLINE,
  SMOKE_STAGE6_COMMITTEE_ID,
  SMOKE_FILINGS_PAGED_COMMITTEE_ID,
  SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID,
  SMOKE_FILINGS_PAGE_1_FIRST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_1_LAST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_2_FIRST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_2_LAST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_1_LABEL,
  SMOKE_FILINGS_PAGE_2_LABEL,
  SMOKE_FILINGS_HIGH_TOTAL_LABEL
} from "../../../tests/smoke/fixtures";
import { smokeFixtures } from "../../../tests/smoke/fixture-data";
import {
  COMMITTEE_FILINGS_PAGE_SIZE,
  COMMITTEE_SUMMARY_SOURCE_LABELS,
  buildCommitteeItemizedCoverageNote,
  buildPaginatedCommitteeFilingBreakdown
} from "./presentation";

const fixturesSource = readFileSync(
  resolve(__dirname, "../../../tests/smoke/fixtures.ts"),
  "utf-8"
);

function assignmentRHS(source: string, constName: string): string {
  const pattern = new RegExp(
    `export\\s+const\\s+${constName}\\s*=\\s*(.+?)\\s*;`
  );
  const match = source.match(pattern);
  if (!match) {
    throw new Error(`Could not find export const ${constName} in fixtures.ts`);
  }
  return match[1].trim();
}

function seededReceiptAmounts(seedSql: string): number[] {
  return [...seedSql.matchAll(/'smoke-congress-receipt-[^']+',\s*'2026-\d{2}-\d{2}',\s*([0-9.]+)/g)].map(
    (match) => Number(match[1])
  );
}

function seededCommitteeSummaryAmounts(seedSql: string): {
  totalReceipts: number;
  unitemizedReceipts: number;
} {
  const blockStart = seedSql.indexOf("INSERT INTO cf.committee_summary");
  const blockEnd = seedSql.indexOf("INSERT INTO civic.zcta_district", blockStart);
  if (blockStart === -1 || blockEnd === -1) {
    throw new Error("Could not find committee_summary seed values");
  }
  const block = seedSql.slice(blockStart, blockEnd);

  const rows = [
    ...block.matchAll(
      /'20\d{2}-\d{2}-\d{2}',\s*([0-9.]+),\s*[0-9.]+,\s*[0-9.]+,\s*([0-9.]+)/g
    )
  ];
  if (rows.length === 0) {
    throw new Error("Could not find committee_summary amount rows");
  }

  return rows.reduce(
    (totals, match) => ({
      totalReceipts: totals.totalReceipts + Number(match[1]),
      unitemizedReceipts: totals.unitemizedReceipts + Number(match[2])
    }),
    { totalReceipts: 0, unitemizedReceipts: 0 }
  );
}

function percentHeadline(numerator: number, denominator: number): string {
  return `${Math.round((numerator / denominator) * 100)}%`;
}

describe("smoke fixtures single-source aliases", () => {
  it("SMOKE_CONTEST_WINNER_NAME is aliased to SMOKE_CANDIDACY_PERSON_NAME, not a string literal", () => {
    expect(assignmentRHS(fixturesSource, "SMOKE_CONTEST_WINNER_NAME")).toBe(
      "SMOKE_CANDIDACY_PERSON_NAME"
    );
  });

  it("SMOKE_OFFICE_RECENT_CONTEST_NAME is aliased to SMOKE_CONTEST_NAME, not a string literal", () => {
    expect(assignmentRHS(fixturesSource, "SMOKE_OFFICE_RECENT_CONTEST_NAME")).toBe(
      "SMOKE_CONTEST_NAME"
    );
  });

  it("routes the seeded Stage 6 committee by stable fixture id instead of its collidable slug", () => {
    expect(getSeededStage6CommitteeRoute().committeePath).toBe(
      `/committee/${SMOKE_STAGE6_COMMITTEE_ID}`
    );
  });

  it("smoke fixtures use COMMITTEE_SUMMARY_SOURCE_LABELS from presentation.ts, not duplicate literals", () => {
    expect(fixturesSource).not.toContain('"Official FEC committee summary"');
    expect(fixturesSource).not.toContain('"Derived from itemized transactions"');
    expect(fixturesSource).toContain("COMMITTEE_SUMMARY_SOURCE_LABELS");
  });

  it("smoke fixtures use buildCommitteeItemizedCoverageNote from presentation.ts, not a duplicate builder", () => {
    expect(fixturesSource).not.toMatch(
      /function\s+buildSmokeItemizedCoverageNote/
    );
    expect(fixturesSource).toContain("buildCommitteeItemizedCoverageNote");
  });

  it("seeded smoke constants derive from the canonical presenter", () => {
    const seeded = getSeededStage6CommitteeRoute();
    expect(seeded.expectedSummarySourceLabel).toBe(
      COMMITTEE_SUMMARY_SOURCE_LABELS.fec_committee_summary
    );
    expect(seeded.expectedItemizedCoverageNote).toBe(
      buildCommitteeItemizedCoverageNote({
        itemized_transaction_count: 0,
        summary_source: "fec_committee_summary"
      })
    );
  });

  it("fixture-mode person contribution insights match backend codes and share math", () => {
    const insights = smokeFixtures.person.contributionInsights;

    expect(insights.metadata.excluded_geography).toBeNull();
    expect(insights.metadata.caveats).toEqual([]);

    const smallDollarAmount = Number(insights.small_dollar_share.small_dollar_amount);
    const totalContributionAmount = Number(insights.small_dollar_share.total_contribution_amount);
    const share = Number(insights.small_dollar_share.share);

    expect(Number.isFinite(smallDollarAmount)).toBe(true);
    expect(Number.isFinite(totalContributionAmount)).toBe(true);
    expect(Number.isFinite(share)).toBe(true);
    expect(totalContributionAmount).toBeGreaterThan(0);
    expect(share).toBeCloseTo(smallDollarAmount / totalContributionAmount, 4);
  });

  it("live-mode seeded person small-dollar headline matches the exported smoke expectation", () => {
    const seedSql = buildCongressSmokeSeedSql();
    const { totalReceipts, unitemizedReceipts } = seededCommitteeSummaryAmounts(seedSql);
    const smallItemizedReceipts = seededReceiptAmounts(seedSql)
      .filter((amount) => amount <= 200)
      .reduce((total, amount) => total + amount, 0);

    expect(percentHeadline(unitemizedReceipts + smallItemizedReceipts, totalReceipts)).toBe(
      SMOKE_PERSON_SMALL_DOLLAR_HEADLINE
    );
  });

  it("derives fallback live committee assertions from discovered API records", async () => {
    const apiResponses = new Map<string, { ok: boolean; status: number; body: unknown }>([
      ["/v1/committees/by-slug/mike-johnson-for-louisiana", { ok: false, status: 404, body: {} }],
      [
        "/v1/search?q=MIKE%20JOHNSON%20FOR%20LOUISIANA&entity_type=committee",
        {
          ok: true,
          status: 200,
          body: {
            results: [
              {
                id: "live-committee-id",
                name: "MIKE JOHNSON FOR LOUISIANA",
                slug: "mike-johnson-for-louisiana",
                slug_is_unique: true
              }
            ]
          }
        }
      ],
      [
        "/v1/committees/live-committee-id",
        {
          ok: true,
          status: 200,
          body: {
            linked_candidates: [
              {
                name: "LIVE MIKE JOHNSON"
              }
            ]
          }
        }
      ],
      [
        "/v1/committees/live-committee-id/summary",
        {
          ok: true,
          status: 200,
          body: {
            total_raised: "2345678.90",
            itemized_transaction_count: 17,
            summary_source: "fec_committee_summary",
            cycle_summaries: [{ cycle: 2026 }]
          }
        }
      ],
      [
        "/v1/committees/live-committee-id/independent-expenditures-made",
        {
          ok: true,
          status: 200,
          body: {
            ie_transaction_count: 1,
            targets: [{ candidate_name: "LIVE IE TARGET" }]
          }
        }
      ]
    ]);
    const page = {
      request: {
        get: async (url: string) => {
          const parsed = new URL(url);
          const response = apiResponses.get(`${parsed.pathname}${parsed.search}`);
          if (response === undefined) {
            throw new Error(`Unexpected API request: ${url}`);
          }
          return {
            ok: () => response.ok,
            status: () => response.status,
            json: async () => response.body
          };
        }
      }
    };

    const discovery = await discoverLiveLouisianaCommitteeRoute(page);

    expect(discovery).toEqual({
      committeePath: "/committee/mike-johnson-for-louisiana",
      expectedSummarySourceLabel: "Official FEC committee summary",
      expectedItemizedCoverageNote:
        "Itemized transactions loaded: 17. Official totals above come directly from the FEC committee summary and are not derived from these transactions.",
      expectedLinkedCandidateName: "LIVE MIKE JOHNSON",
      expectedCycleLabel: "2026",
      expectedTotalRaisedText: "$2,345,678.90",
      expectedOutsideSpendingEmptyText: null,
      expectedOutsideSpendingTargetName: "LIVE IE TARGET"
    });
  });
});

function renderedFilingRowLabel(row: { filingName: string; filingFecId: string }): string {
  // Mirrors the DetailPage.svelte filing cell: `{row.filingName} ({row.filingFecId})`.
  return `${row.filingName} (${row.filingFecId})`;
}

describe("filing pagination smoke fixtures", () => {
  it("paged committee fixture is a 30-row window carrying backend pagination metadata", () => {
    const fixture = smokeFixtures.committeeFilingsPaged;
    expect(fixture.id).toBe(SMOKE_FILINGS_PAGED_COMMITTEE_ID);
    expect(fixture.filingBreakdown.filings).toHaveLength(30);
    expect(fixture.filingBreakdown.total_filings).toBe(30);
    expect(fixture.filingBreakdown.store_limit).toBe(200);
    expect(fixture.filingBreakdown.has_next).toBe(false);
    expect(fixture.filingBreakdown.offset).toBe(0);
    expect(fixture.filingBreakdown.limit).toBe(200);
  });

  it("high-total committee fixture fetches the full 200-row window over a larger all-time count", () => {
    const fixture = smokeFixtures.committeeFilingsHighTotal;
    expect(fixture.id).toBe(SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID);
    expect(fixture.filingBreakdown.filings).toHaveLength(200);
    expect(fixture.filingBreakdown.total_filings).toBe(220706);
    expect(fixture.filingBreakdown.store_limit).toBe(200);
  });

  it("exported page-1/page-2 labels and row identities match the real presenter", () => {
    const { filingBreakdown } = smokeFixtures.committeeFilingsPaged;
    const pageOne = buildPaginatedCommitteeFilingBreakdown(filingBreakdown, "0");
    const pageTwo = buildPaginatedCommitteeFilingBreakdown(
      filingBreakdown,
      String(COMMITTEE_FILINGS_PAGE_SIZE)
    );

    expect(pageOne.label).toBe(SMOKE_FILINGS_PAGE_1_LABEL);
    expect(pageTwo.label).toBe(SMOKE_FILINGS_PAGE_2_LABEL);

    expect(pageOne.rows).toHaveLength(25);
    expect(pageTwo.rows).toHaveLength(5);

    expect(renderedFilingRowLabel(pageOne.rows[0])).toBe(SMOKE_FILINGS_PAGE_1_FIRST_ROW_LABEL);
    expect(renderedFilingRowLabel(pageOne.rows[24])).toBe(SMOKE_FILINGS_PAGE_1_LAST_ROW_LABEL);
    expect(renderedFilingRowLabel(pageTwo.rows[0])).toBe(SMOKE_FILINGS_PAGE_2_FIRST_ROW_LABEL);
    expect(renderedFilingRowLabel(pageTwo.rows[4])).toBe(SMOKE_FILINGS_PAGE_2_LAST_ROW_LABEL);
  });

  it("exported high-total label matches the real presenter for the 200-row window", () => {
    const { filingBreakdown } = smokeFixtures.committeeFilingsHighTotal;
    const pageOne = buildPaginatedCommitteeFilingBreakdown(filingBreakdown, "0");
    expect(pageOne.label).toBe(SMOKE_FILINGS_HIGH_TOTAL_LABEL);
  });

  it("filing pagination fixtures use a summary_source known to COMMITTEE_SUMMARY_SOURCE_LABELS", () => {
    expect(COMMITTEE_SUMMARY_SOURCE_LABELS).toHaveProperty(
      smokeFixtures.committeeFilingsPaged.summary.summary_source
    );
    expect(COMMITTEE_SUMMARY_SOURCE_LABELS).toHaveProperty(
      smokeFixtures.committeeFilingsHighTotal.summary.summary_source
    );
  });
});
