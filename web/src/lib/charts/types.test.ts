import { describe, expectTypeOf, it } from "vitest";
import type {
  CashOnHandPoint,
  ChartFrameProps,
  ChartKind,
  ChartPoint,
  ChartProps,
  ChartSeries,
  ExactDisclosureRow,
  FigureSummary,
  GeographyShareRow,
  HorizontalBarRow,
  MonthlyContributionRow,
  OutsideSpendingRow,
  ReceiptCompositionRow
} from "./types";

describe("charts/types", () => {
  it("exports a single chart kind union contract", () => {
    expectTypeOf<ChartKind>().toEqualTypeOf<"line" | "bar">();
  });

  it("enforces typed points and series for downstream consumers", () => {
    const point: ChartPoint = { x: "2026-01-01", y: 42 };
    const series: ChartSeries = {
      id: "raised",
      label: "Raised",
      points: [point]
    };
    const props: ChartProps = {
      kind: "line",
      title: "Weekly receipts",
      ariaLabel: "Weekly receipts trend",
      series: [series]
    };

    expectTypeOf(point.y).toEqualTypeOf<number>();
    expectTypeOf<ChartSeries["points"][number]>().toEqualTypeOf<ChartPoint>();
    expectTypeOf<ChartProps["series"][number]>().toEqualTypeOf<ChartSeries>();
  });

  it("exports finance chart frame metadata without generic x/y props", () => {
    const exactRows: ExactDisclosureRow[] = [
      {
        label: "Unknown",
        values: [
          { label: "Dollars", value: "$125.00" },
          { label: "Transactions", value: "3" },
          { label: "Source filing", value: "FEC filing F123", href: "https://www.fec.gov/data/" }
        ]
      }
    ];
    const summary: FigureSummary = {
      sentence: "Unknown geography accounts for $125.00 of $1,000.00 in the 2026 cycle."
    };
    const frame: ChartFrameProps = {
      testId: "geography-share",
      title: "Geography",
      unit: "dollars",
      cycle: 2026,
      coverageThrough: "2026-06-30",
      summary,
      sources: [{ label: "FEC Schedule A", href: "https://www.fec.gov/data/" }],
      exactRows,
      state: { kind: "ready" }
    };

    expectTypeOf(frame.cycle).toEqualTypeOf<number>();
    expectTypeOf(frame.coverageThrough).toEqualTypeOf<string | null>();
    expectTypeOf(frame.unit).toEqualTypeOf<ChartFrameProps["unit"]>();
    expectTypeOf(frame.sources[0].label).toEqualTypeOf<string>();
    expectTypeOf(frame.exactRows).toEqualTypeOf<ExactDisclosureRow[]>();

    // @ts-expect-error Finance chart frames do not accept the legacy generic x/y grammar.
    frame.series = [];
  });

  it("carries finance rows with denominators, Unknown rows, and exact disclosure values", () => {
    const receipts: ReceiptCompositionRow[] = [
      {
        id: "individual",
        label: "Gross individual contributions",
        amount: 700,
        denominator: 1000,
        canPlot: true
      }
    ];
    const monthly: MonthlyContributionRow[] = [
      { month: "2026-01", amount: 0, transactionCount: 0, covered: true },
      { month: "2026-02", amount: 250, transactionCount: 2, covered: true }
    ];
    const cash: CashOnHandPoint[] = [
      { periodEnd: "2026-03-31", amount: 1200, missingIntervalBefore: false }
    ];
    const bars: HorizontalBarRow[] = [
      {
        id: "200-under",
        label: "$200 and under",
        amount: 500,
        transactionCount: 10,
        unit: "reported_transactions",
        canPlot: true
      }
    ];
    const geography: GeographyShareRow[] = [
      {
        id: "unknown",
        label: "Unknown",
        amount: 125,
        transactionCount: 3,
        denominator: 1000,
        approximate: false
      }
    ];
    const outside: OutsideSpendingRow[] = [
      {
        id: "support",
        label: "Support spending",
        stance: "support",
        amount: 400,
        transactionCount: 4,
        sourceHref: "https://www.fec.gov/data/filings/F123/"
      }
    ];

    expectTypeOf(receipts[0].denominator).toEqualTypeOf<number>();
    expectTypeOf(monthly[0].month).toEqualTypeOf<string>();
    expectTypeOf(cash[0].periodEnd).toEqualTypeOf<string>();
    expectTypeOf(bars[0].unit).toEqualTypeOf<HorizontalBarRow["unit"]>();
    expectTypeOf(bars[0].canPlot).toEqualTypeOf<boolean>();
    expectTypeOf(geography[0].label).toEqualTypeOf<string>();
    expectTypeOf(outside[0].stance).toEqualTypeOf<"support" | "oppose">();
    expectTypeOf(outside[0].sourceHref).toEqualTypeOf<string | undefined>();

    // @ts-expect-error Finance rows are derived facts, not generic chart points.
    receipts[0].x = "2026-01";
    // @ts-expect-error Finance rows are derived facts, not generic chart points.
    monthly[0].y = 42;
  });

  it("models no-data and table-only chart states explicitly", () => {
    const noData: ChartFrameProps["state"] = {
      kind: "no-data",
      message: "No itemized individual contribution rows are loaded yet."
    };
    const tableOnly: ChartFrameProps["state"] = {
      kind: "table-only",
      message: "Source components do not reconcile cleanly enough for a proportional plot."
    };

    expectTypeOf(noData.kind).toEqualTypeOf<"no-data">();
    expectTypeOf(tableOnly.kind).toEqualTypeOf<"table-only">();
  });
});
