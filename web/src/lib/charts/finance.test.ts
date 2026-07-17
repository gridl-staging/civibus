import { describe, expect, it } from "vitest";
import {
  FEC_SIZE_BUCKET_LABELS,
  FINANCE_CHART_COLORS,
  buildCashOnHandSeries,
  calculateOutsideSpendingDomain,
  formatCurrency,
  formatCurrencyShort,
  formatCount,
  formatPercent,
  getContrastRatio,
  getReadableTickCeiling,
  orderByUtcMonthKey,
  summarizeShare,
  zeroFillCoveredMonths
} from "./finance";
import type {
  CashOnHandPoint,
  GeographyShareRow,
  MonthlyContributionRow,
  OutsideSpendingRow
} from "./types";

describe("charts/finance helpers", () => {
  it("formats hand-calculated currency, counts, and percentages", () => {
    expect(formatCurrency(1250.5)).toBe("$1,250.50");
    expect(formatCurrency(-25.25)).toBe("-$25.25");
    expect(formatCurrencyShort(300_000)).toBe("$300K");
    expect(formatCurrencyShort(1_500_000)).toBe("$1.5M");
    expect(formatCurrencyShort(950)).toBe("$950");
    expect(formatCount(1234)).toBe("1,234");
    expect(formatPercent(0.125)).toBe("12.5%");
    expect(formatPercent(0)).toBe("0%");
  });

  it("zero-fills covered UTC months only and preserves month ordering", () => {
    const rows: MonthlyContributionRow[] = [
      { month: "2026-03", amount: 300, transactionCount: 3, covered: true },
      { month: "2026-01", amount: 100, transactionCount: 1, covered: true }
    ];

    expect(orderByUtcMonthKey(rows).map((row) => row.month)).toEqual(["2026-01", "2026-03"]);
    expect(
      zeroFillCoveredMonths(rows, ["2026-01", "2026-02", "2026-03"]).map((row) => ({
        month: row.month,
        amount: row.amount,
        count: row.transactionCount,
        covered: row.covered
      }))
    ).toEqual([
      { month: "2026-01", amount: 100, count: 1, covered: true },
      { month: "2026-02", amount: 0, count: 0, covered: true },
      { month: "2026-03", amount: 300, count: 3, covered: true }
    ]);
  });

  it("preserves source monthly rows when coverage metadata is empty or incomplete", () => {
    const rows: MonthlyContributionRow[] = [
      { month: "2026-03", amount: 300, transactionCount: 3, covered: false },
      { month: "2026-01", amount: 100, transactionCount: 1, covered: true }
    ];

    expect(zeroFillCoveredMonths(rows, []).map((row) => row.month)).toEqual([
      "2026-01",
      "2026-03"
    ]);
    expect(
      zeroFillCoveredMonths(rows, ["2026-02"]).map((row) => ({
        month: row.month,
        amount: row.amount,
        count: row.transactionCount,
        covered: row.covered
      }))
    ).toEqual([
      { month: "2026-01", amount: 100, count: 1, covered: true },
      { month: "2026-02", amount: 0, count: 0, covered: true },
      { month: "2026-03", amount: 300, count: 3, covered: false }
    ]);
  });

  it("selects readable tick ceilings without hiding the maximum value", () => {
    expect(getReadableTickCeiling(0)).toBe(0);
    expect(getReadableTickCeiling(999)).toBe(1000);
    expect(getReadableTickCeiling(1001)).toBe(1250);
    expect(getReadableTickCeiling(126000)).toBe(150000);
  });

  it("splits cash-on-hand series at explicit missing intervals without dropping points", () => {
    const points: CashOnHandPoint[] = [
      { periodEnd: "2026-09-30", amount: 1800, missingIntervalBefore: false },
      { periodEnd: "2026-03-31", amount: 1200, missingIntervalBefore: false },
      { periodEnd: "2026-06-30", amount: 1400, missingIntervalBefore: true }
    ];

    expect(buildCashOnHandSeries(points)).toEqual([
      {
        id: "cash_on_hand_segment_1",
        label: "Cash on hand",
        points: [{ x: new Date("2026-03-31T00:00:00.000Z"), y: 1200 }]
      },
      {
        id: "cash_on_hand_segment_2",
        label: "Cash on hand",
        points: [
          { x: new Date("2026-06-30T00:00:00.000Z"), y: 1400 },
          { x: new Date("2026-09-30T00:00:00.000Z"), y: 1800 }
        ]
      }
    ]);
  });

  it("preserves the FEC size-bucket label order accepted by the screen spec", () => {
    expect(FEC_SIZE_BUCKET_LABELS).toEqual([
      "$200 and under",
      "$200.01-$499.99",
      "$500-$999.99",
      "$1,000-$1,999.99",
      "$2,000 and over"
    ]);
  });

  it("builds denominator-aware geography share summaries", () => {
    const row: GeographyShareRow = {
      id: "unknown",
      label: "Unknown",
      amount: 125,
      transactionCount: 3,
      denominator: 1000,
      approximate: true
    };

    expect(summarizeShare(row)).toBe("Unknown is $125.00 of $1,000.00 (12.5%).");
  });

  it("calculates support and oppose signs around a zero-centered domain", () => {
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

    expect(calculateOutsideSpendingDomain(rows)).toEqual({
      min: -400,
      max: 400,
      signedRows: [
        { id: "support", label: "Support spending", signedAmount: 400 },
        { id: "oppose", label: "Oppose spending", signedAmount: -250 }
      ]
    });
  });

  it("keeps support and oppose colors above WCAG contrast thresholds", () => {
    expect(getContrastRatio(FINANCE_CHART_COLORS.support, "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(getContrastRatio(FINANCE_CHART_COLORS.oppose, "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(getContrastRatio(FINANCE_CHART_COLORS.support, "#f8fafc")).toBeGreaterThanOrEqual(3);
    expect(getContrastRatio(FINANCE_CHART_COLORS.oppose, "#f8fafc")).toBeGreaterThanOrEqual(3);
  });
});
