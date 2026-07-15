import { render } from "svelte/server";
import { describe, expect, it } from "vitest";

import CashOnHandTrendChart from "./CashOnHandTrendChart.svelte";
import ChartFrame from "./ChartFrame.svelte";
import GeographyShareChart from "./GeographyShareChart.svelte";
import HorizontalBarChart from "./HorizontalBarChart.svelte";
import MonthlyContributionsChart from "./MonthlyContributionsChart.svelte";
import OutsideSpendingChart from "./OutsideSpendingChart.svelte";
import ReceiptCompositionChart from "./ReceiptCompositionChart.svelte";
import type {
  CashOnHandPoint,
  ChartFrameProps,
  GeographyShareRow,
  HorizontalBarRow,
  MonthlyContributionRow,
  OutsideSpendingRow,
  ReceiptCompositionRow
} from "./types";

const baseFrame = {
  cycle: 2026,
  coverageThrough: "2026-06-30",
  sources: [{ label: "FEC filings", href: "https://www.fec.gov/data/" }]
} satisfies Pick<ChartFrameProps, "cycle" | "coverageThrough" | "sources">;

function expectFigureContract(html: string, testId: string, title: string): void {
  expect(html).toContain("<figure");
  expect(html).toContain("<figcaption");
  expect(html).toContain(`data-testid="${testId}"`);
  expect(html).toContain(title);
  expect(html).toContain("2026 cycle");
  expect(html).toContain("coverage through June 30, 2026");
  expect(html).toContain("FEC filings");
  expect(html).toContain("<details");
  expect(html).toMatch(/<summary[^>]*>View chart data<\/summary>/);
}

describe("finance chart SSR components", () => {
  it("renders the shared frame as a semantic figure with no-data and exact-table states", () => {
    const rendered = render(ChartFrame, {
      props: {
        ...baseFrame,
        testId: "chart-frame-contract",
        title: "Itemized individual contributions by month",
        unit: "dollars",
        summary: {
          sentence: "Itemized individual contributions total $300.00 in the 2026 cycle."
        },
        exactRows: [
          {
            label: "January 2026",
            values: [
              { label: "Dollars", value: "$100.00" },
              { label: "Transactions", value: "1" }
            ]
          }
        ],
        state: {
          kind: "no-data",
          message: "No itemized individual contribution rows are loaded yet."
        }
      }
    });

    expectFigureContract(
      rendered.body,
      "chart-frame-contract",
      "Itemized individual contributions by month"
    );
    expect(rendered.body).toContain(
      "Itemized individual contributions total $300.00 in the 2026 cycle."
    );
    expect(rendered.body).toContain("Unit: dollars");
    expect(rendered.body).toContain("No itemized individual contribution rows are loaded yet.");
    expect(rendered.body).toContain("January 2026");
    expect(rendered.body).toContain("$100.00");
  });

  it("renders linked values in the exact disclosure table", () => {
    const rendered = render(ChartFrame, {
      props: {
        ...baseFrame,
        testId: "chart-frame-linked-values",
        title: "Outside spending",
        unit: "dollars",
        summary: {
          sentence: "Outside spending reports $400.00 in support spending for the 2026 cycle."
        },
        exactRows: [
          {
            label: "Top spender: Example PAC",
            values: [
              {
                label: "Source filing",
                value: "FEC filing F123",
                href: "https://www.fec.gov/data/filings/F123/"
              }
            ]
          }
        ],
        state: { kind: "ready" }
      }
    });

    expect(rendered.body).toContain(
      '<a href="https://www.fec.gov/data/filings/F123/">FEC filing F123</a>'
    );
  });

  it("renders receipt composition and suppresses proportional output when reconciliation fails", () => {
    const rows: ReceiptCompositionRow[] = [
      {
        id: "individual",
        label: "Gross individual contributions",
        amount: 700,
        denominator: 1000,
        canPlot: false
      },
      {
        id: "other",
        label: "Residual other receipts",
        amount: 325,
        denominator: 1000,
        canPlot: false
      }
    ];
    const rendered = render(ReceiptCompositionChart, {
      props: {
        ...baseFrame,
        testId: "receipt-composition",
        rows,
        totalReceipts: 1000,
        canPlot: false,
        caveat: "Source components do not reconcile cleanly enough for a proportional plot."
      }
    });

    expectFigureContract(rendered.body, "receipt-composition", "Sources of receipts");
    expect(rendered.body).toContain(
      "Source components do not reconcile cleanly enough for a proportional plot."
    );
    expect(rendered.body).toContain("Gross individual contributions");
    expect(rendered.body).toContain("$700.00");
    expect(rendered.body).not.toContain('data-testid="receipt-composition-plot"');
  });

  it("renders missing receipt components as no-data instead of a reconciliation caveat", () => {
    const rendered = render(ReceiptCompositionChart, {
      props: {
        ...baseFrame,
        testId: "receipt-composition-empty",
        rows: [],
        totalReceipts: 1000,
        canPlot: true
      }
    });

    expectFigureContract(rendered.body, "receipt-composition-empty", "Sources of receipts");
    expect(rendered.body).toContain("Receipt source components are not loaded yet.");
    expect(rendered.body).not.toContain(
      "Source components do not reconcile cleanly enough for a proportional plot."
    );
    expect(rendered.body).not.toContain('data-testid="receipt-composition-empty-plot"');
  });

  it("exposes receipt composition share values in the exact disclosure", () => {
    const rows: ReceiptCompositionRow[] = [
      {
        id: "individual",
        label: "Gross individual contributions",
        amount: 700,
        denominator: 1000,
        canPlot: true
      }
    ];
    const rendered = render(ReceiptCompositionChart, {
      props: {
        ...baseFrame,
        testId: "receipt-composition-share-disclosure",
        rows,
        totalReceipts: 1000,
        canPlot: true
      }
    });

    expect(rendered.body).toMatch(/Share:[\s\S]*70%/);
  });

  it("renders monthly contribution columns with zero-filled covered months and counts", () => {
    const rows: MonthlyContributionRow[] = [
      { month: "2026-01", amount: 100, transactionCount: 1, covered: true },
      { month: "2026-03", amount: 300, transactionCount: 3, covered: true }
    ];
    const rendered = render(MonthlyContributionsChart, {
      props: {
        ...baseFrame,
        testId: "monthly-contributions",
        rows,
        coveredMonths: ["2026-01", "2026-02", "2026-03"]
      }
    });

    expectFigureContract(
      rendered.body,
      "monthly-contributions",
      "Itemized individual contributions by month"
    );
    expect(rendered.body).toContain("Unit: dollars");
    expect(rendered.body).toContain("February 2026");
    expect(rendered.body).toContain("$0.00");
    expect(rendered.body).toContain("3 transactions");
    expect(rendered.body).toContain('data-testid="monthly-contributions-plot"');
    expect(rendered.body).toContain("chart-wrapper");
    expect(rendered.body).toContain("Monthly contribution columns");
  });

  it("renders monthly contributions through the package-backed chart seam", () => {
    const rows: MonthlyContributionRow[] = [
      { month: "2026-01", amount: 100, transactionCount: 1, covered: true },
      { month: "2026-02", amount: 250, transactionCount: 2, covered: true }
    ];
    const rendered = render(MonthlyContributionsChart, {
      props: {
        ...baseFrame,
        testId: "monthly-chart-seam",
        rows,
        coveredMonths: ["2026-01", "2026-02"]
      }
    });

    expect(rendered.body).toContain("chart-wrapper__body");
    expect(rendered.body).not.toContain("Readable tick ceiling:");
  });

  it("renders source monthly rows even when covered months are incomplete", () => {
    const rows: MonthlyContributionRow[] = [
      { month: "2026-03", amount: 300, transactionCount: 3, covered: false }
    ];
    const rendered = render(MonthlyContributionsChart, {
      props: {
        ...baseFrame,
        testId: "monthly-incomplete-coverage",
        rows,
        coveredMonths: ["2026-02"]
      }
    });

    expect(rendered.body).toContain("February 2026");
    expect(rendered.body).toContain("March 2026");
    expect(rendered.body).toContain("$300.00");
    expect(rendered.body).toContain("Missing source coverage");
  });

  it("renders cash-on-hand trends only when at least two dated values exist", () => {
    const points: CashOnHandPoint[] = [
      { periodEnd: "2026-03-31", amount: 1200, missingIntervalBefore: false },
      { periodEnd: "2026-06-30", amount: 1400, missingIntervalBefore: true }
    ];
    const rendered = render(CashOnHandTrendChart, {
      props: {
        ...baseFrame,
        testId: "cash-on-hand-trend",
        points
      }
    });

    expectFigureContract(rendered.body, "cash-on-hand-trend", "Cash on hand");
    expect(rendered.body).toContain("$1,400.00");
    expect(rendered.body).toContain("Missing source coverage before this filing period.");
    expect(rendered.body).toContain('data-testid="cash-on-hand-trend-plot"');
    expect(rendered.body).toContain("chart-wrapper");
  });

  it("renders ordered horizontal bars with bounded rows and no unitemized bucket", () => {
    const rows: HorizontalBarRow[] = [
      {
        id: "200-under",
        label: "$200 and under",
        amount: 500,
        transactionCount: 10,
        unit: "dollars",
        canPlot: true
      },
      {
        id: "500-999",
        label: "$500-$999.99",
        amount: 250,
        transactionCount: 1,
        unit: "dollars",
        canPlot: true
      }
    ];
    const rendered = render(HorizontalBarChart, {
      props: {
        ...baseFrame,
        testId: "size-buckets",
        title: "Itemized contribution-size buckets",
        rows
      }
    });

    expectFigureContract(rendered.body, "size-buckets", "Itemized contribution-size buckets");
    expect(rendered.body.indexOf("$200 and under")).toBeLessThan(
      rendered.body.indexOf("$500-$999.99")
    );
    expect(rendered.body).toContain("10 reported transactions");
    expect(rendered.body).toContain('data-testid="size-buckets-plot"');
    expect(rendered.body).not.toContain("Unitemized");
  });

  it("scales reported-transaction horizontal bars by transaction count", () => {
    const rows: HorizontalBarRow[] = [
      {
        id: "high-dollars-low-count",
        label: "High dollars, low count",
        amount: 1000,
        transactionCount: 1,
        unit: "reported_transactions",
        canPlot: true
      },
      {
        id: "low-dollars-high-count",
        label: "Low dollars, high count",
        amount: 100,
        transactionCount: 4,
        unit: "reported_transactions",
        canPlot: true
      }
    ];
    const rendered = render(HorizontalBarChart, {
      props: {
        ...baseFrame,
        testId: "transaction-bars",
        title: "Reported transaction buckets",
        rows
      }
    });

    expect(rendered.body).toMatch(
      /High dollars, low count[\s\S]*--finance-width: 25%[\s\S]*Low dollars, high count[\s\S]*--finance-width: 100%/
    );
  });

  it("keeps unitemized source rows in exact disclosure while suppressing them from the plot", () => {
    const rows: HorizontalBarRow[] = [
      {
        id: "itemized",
        label: "Itemized individual contributions",
        amount: 500,
        transactionCount: 10,
        unit: "dollars",
        canPlot: true
      },
      {
        id: "unitemized",
        label: "Unitemized official summary",
        amount: 125,
        transactionCount: 0,
        unit: "dollars",
        canPlot: false
      }
    ];
    const rendered = render(HorizontalBarChart, {
      props: {
        ...baseFrame,
        testId: "horizontal-unitemized-disclosure",
        title: "Itemized contribution-size buckets",
        rows
      }
    });
    const plotHtml = rendered.body.slice(
      rendered.body.indexOf('data-testid="horizontal-unitemized-disclosure-plot"'),
      rendered.body.indexOf("<details")
    );

    expect(plotHtml).toContain("Itemized individual contributions");
    expect(plotHtml).not.toContain("Unitemized official summary");
    expect(rendered.body).toContain("Unitemized official summary");
    expect(rendered.body).toContain("$125.00");
  });

  it("renders geography shares with Unknown and visible denominators", () => {
    const rows: GeographyShareRow[] = [
      {
        id: "in-state",
        label: "In state",
        amount: 875,
        transactionCount: 8,
        denominator: 1000,
        approximate: false
      },
      {
        id: "unknown",
        label: "Unknown",
        amount: 125,
        transactionCount: 3,
        denominator: 1000,
        approximate: true
      }
    ];
    const rendered = render(GeographyShareChart, {
      props: {
        ...baseFrame,
        testId: "geography-share",
        rows,
        unknownIncludedInDenominator: true,
        approximationNote:
          "ZIP5 district approximation uses Census 119th-Congress / 2020-ZCTA relationships."
      }
    });

    expectFigureContract(rendered.body, "geography-share", "Geography");
    expect(rendered.body).toContain("Unknown");
    expect(rendered.body).toContain("$125.00 of $1,000.00");
    expect(rendered.body).toContain(
      "Unknown is included in the visible geography denominator. Unknown is $125.00 with 3 reported transactions; visible denominator is $1,000.00."
    );
    expect(rendered.body).not.toContain("outside the classified geography denominator");
    expect(rendered.body).toContain(
      "ZIP5 district approximation uses Census 119th-Congress / 2020-ZCTA relationships."
    );
  });

  it("keeps empty geography input in the no-data state", () => {
    const rendered = render(GeographyShareChart, {
      props: {
        ...baseFrame,
        testId: "geography-empty",
        rows: []
      }
    });

    expectFigureContract(rendered.body, "geography-empty", "Geography");
    expect(rendered.body).toContain("No geography rows are loaded yet.");
    expect(rendered.body).not.toContain('data-testid="geography-empty-plot"');
    expect(rendered.body).not.toContain("Unknown is $0.00 of $0.00");
  });

  it("does not fabricate a zero Unknown geography row when the required row is missing", () => {
    const rendered = render(GeographyShareChart, {
      props: {
        ...baseFrame,
        testId: "geography-missing-unknown",
        rows: [
          {
            id: "in-state",
            label: "In state",
            amount: 875,
            transactionCount: 8,
            denominator: 1000,
            approximate: false
          }
        ]
      }
    });

    expectFigureContract(rendered.body, "geography-missing-unknown", "Geography");
    expect(rendered.body).toContain("Unknown geography row is required");
    expect(rendered.body).toContain("In state");
    expect(rendered.body).toContain("$875.00");
    expect(rendered.body).not.toContain('data-testid="geography-missing-unknown-plot"');
    expect(rendered.body).not.toContain("Unknown is $0.00 of $1,000.00");
  });

  it("renders outside spending with support and oppose labels around zero", () => {
    const rows: OutsideSpendingRow[] = [
      {
        id: "support",
        label: "Support spending",
        stance: "support",
        amount: 400,
        transactionCount: 4
      },
      {
        id: "oppose",
        label: "Oppose spending",
        stance: "oppose",
        amount: 250,
        transactionCount: 2
      }
    ];
    const rendered = render(OutsideSpendingChart, {
      props: {
        ...baseFrame,
        testId: "outside-spending",
        rows,
        topSpenders: [
          {
            id: "spender-1",
            label: "Example PAC",
            stance: "support",
            amount: 400,
            transactionCount: 4
          }
        ]
      }
    });

    expectFigureContract(rendered.body, "outside-spending", "Outside spending");
    expect(rendered.body).toContain("Support spending");
    expect(rendered.body).toContain("Oppose spending");
    expect(rendered.body).toContain("Top spenders");
    expect(rendered.body).toContain("Transactions");
    expect(rendered.body).toContain('data-zero-centered="true"');
    expect(rendered.body).toContain("chart-wrapper");
  });

  it("carries outside-spending source filing links into exact disclosure rows", () => {
    const rows: OutsideSpendingRow[] = [
      {
        id: "support",
        label: "Support spending",
        stance: "support",
        amount: 400,
        transactionCount: 4,
        sourceHref: "https://www.fec.gov/data/filings/F456/"
      }
    ];
    const rendered = render(OutsideSpendingChart, {
      props: {
        ...baseFrame,
        testId: "outside-spending-links",
        rows,
        topSpenders: [
          {
            id: "spender-1",
            label: "Example PAC",
            stance: "support",
            amount: 400,
            transactionCount: 4,
            sourceHref: "https://www.fec.gov/data/filings/F123/"
          }
        ]
      }
    });

    expect(rendered.body).toContain(
      '<a href="https://www.fec.gov/data/filings/F123/">Source filing</a>'
    );
    expect(rendered.body).toContain(
      '<a href="https://www.fec.gov/data/filings/F456/">Source filing</a>'
    );
  });

  it("binds outside spending row colors to stance instead of row position", () => {
    const rows: OutsideSpendingRow[] = [
      {
        id: "oppose",
        label: "Oppose spending",
        stance: "oppose",
        amount: 250,
        transactionCount: 2
      },
      {
        id: "support",
        label: "Support spending",
        stance: "support",
        amount: 400,
        transactionCount: 4
      }
    ];
    const rendered = render(OutsideSpendingChart, {
      props: {
        ...baseFrame,
        testId: "outside-spending-reversed",
        rows,
        topSpenders: []
      }
    });

    expect(rendered.body).toMatch(
      /outside-spending__row outside-spending__row--oppose[\s\S]*Oppose spending[\s\S]*outside-spending__row outside-spending__row--support[\s\S]*Support spending/
    );
  });

  it("suppresses outside spending plots when both support and oppose are zero", () => {
    const rendered = render(OutsideSpendingChart, {
      props: {
        ...baseFrame,
        testId: "outside-spending-zero",
        rows: [
          {
            id: "support",
            label: "Support spending",
            stance: "support",
            amount: 0,
            transactionCount: 0
          },
          {
            id: "oppose",
            label: "Oppose spending",
            stance: "oppose",
            amount: 0,
            transactionCount: 0
          }
        ],
        topSpenders: []
      }
    });

    expectFigureContract(rendered.body, "outside-spending-zero", "Outside spending");
    expect(rendered.body).toContain(
      "No independent expenditure support or oppose activity is reported for this cycle."
    );
    expect(rendered.body).not.toContain('data-testid="outside-spending-zero-plot"');
  });
});
