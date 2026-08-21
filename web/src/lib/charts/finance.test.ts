import { describe, expect, it } from "vitest";
import {
  AXIS_VALUE_FORMATTERS,
  FEC_SIZE_BUCKET_LABELS,
  FINANCE_CHART_COLORS,
  TOOLTIP_VALUE_FORMATTERS,
  X_TICK_SPACING_PX,
  bandTickLabelBudgetChars,
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
  truncateTickLabel,
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

  it("abbreviates negative dollars with the sign outside the glyph", () => {
    // The zero-centered support/oppose axis plots negative dollars, and the naive
    // form rendered "$-20000" on every oppose tick.
    expect(formatCurrencyShort(-20_000)).toBe("-$20K");
    expect(formatCurrencyShort(-1_500_000)).toBe("-$1.5M");
    expect(formatCurrencyShort(-950)).toBe("-$950");
    expect(formatCurrencyShort(0)).toBe("$0");
  });

  it("maps every declared chart unit to an axis and a tooltip formatter", () => {
    // Closed rule set: FinanceChartUnit has exactly these four members, and a unit
    // with no entry would make Chart.svelte pass `undefined` to layerchart's axis
    // and silently fall back to a raw number.
    expect(Object.keys(AXIS_VALUE_FORMATTERS).sort()).toEqual([
      "count",
      "dollars",
      "percent",
      "reported_transactions"
    ]);
    expect(Object.keys(TOOLTIP_VALUE_FORMATTERS).sort()).toEqual([
      "count",
      "dollars",
      "percent",
      "reported_transactions"
    ]);

    // The axis abbreviates and the tooltip does not: the axis is for judging scale
    // in a narrow gutter, the tooltip is where the reader asked for the number.
    // 1_250_000 / 1e6 = 1.25, and toFixed(1) rounds half away from zero.
    expect(AXIS_VALUE_FORMATTERS.dollars(1_250_000)).toBe("$1.3M");
    expect(TOOLTIP_VALUE_FORMATTERS.dollars(1_250_000)).toBe("$1,250,000.00");
    expect(AXIS_VALUE_FORMATTERS.percent(0.125)).toBe("12.5%");
    expect(TOOLTIP_VALUE_FORMATTERS.percent(0.125)).toBe("12.5%");
    expect(AXIS_VALUE_FORMATTERS.count(1234)).toBe("1,234");
    expect(TOOLTIP_VALUE_FORMATTERS.count(1234)).toBe("1,234");
    expect(AXIS_VALUE_FORMATTERS.reported_transactions(1234)).toBe("1,234");
    expect(TOOLTIP_VALUE_FORMATTERS.reported_transactions(1234)).toBe("1,234");
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
        points: [
          { x: new Date("2026-03-31T00:00:00.000Z"), y: 1200 },
          { x: new Date("2026-04-01T00:00:00.000Z"), y: 1200 }
        ]
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

  it("preserves a missing interval instead of reconnecting singleton cash-on-hand segments", () => {
    const points: CashOnHandPoint[] = [
      { periodEnd: "2026-06-30", amount: 1400, missingIntervalBefore: true },
      { periodEnd: "2026-03-31", amount: 1200, missingIntervalBefore: false }
    ];

    expect(buildCashOnHandSeries(points)).toEqual([
      {
        id: "cash_on_hand_segment_1",
        label: "Cash on hand",
        points: [
          { x: new Date("2026-03-31T00:00:00.000Z"), y: 1200 },
          { x: new Date("2026-04-01T00:00:00.000Z"), y: 1200 }
        ]
      },
      {
        id: "cash_on_hand_segment_2",
        label: "Cash on hand",
        points: [
          { x: new Date("2026-06-30T00:00:00.000Z"), y: 1400 },
          { x: new Date("2026-07-01T00:00:00.000Z"), y: 1400 }
        ]
      }
    ]);
  });

  it("preserves every explicit gap across unsorted cash-on-hand inputs", () => {
    const points: CashOnHandPoint[] = [
      { periodEnd: "2026-12-31", amount: 2500, missingIntervalBefore: false },
      { periodEnd: "2026-03-31", amount: 1300, missingIntervalBefore: true },
      { periodEnd: "2026-09-30", amount: 2100, missingIntervalBefore: true },
      { periodEnd: "2026-01-31", amount: 1000, missingIntervalBefore: false },
      { periodEnd: "2026-06-30", amount: 1700, missingIntervalBefore: false }
    ];

    expect(buildCashOnHandSeries(points)).toEqual([
      {
        id: "cash_on_hand_segment_1",
        label: "Cash on hand",
        points: [
          { x: new Date("2026-01-31T00:00:00.000Z"), y: 1000 },
          { x: new Date("2026-02-01T00:00:00.000Z"), y: 1000 }
        ]
      },
      {
        id: "cash_on_hand_segment_2",
        label: "Cash on hand",
        points: [
          { x: new Date("2026-03-31T00:00:00.000Z"), y: 1300 },
          { x: new Date("2026-06-30T00:00:00.000Z"), y: 1700 }
        ]
      },
      {
        id: "cash_on_hand_segment_3",
        label: "Cash on hand",
        points: [
          { x: new Date("2026-09-30T00:00:00.000Z"), y: 2100 },
          { x: new Date("2026-12-31T00:00:00.000Z"), y: 2500 }
        ]
      }
    ]);
  });

  it("does not create an empty segment when the first cash-on-hand point is marked", () => {
    const points: CashOnHandPoint[] = [
      { periodEnd: "2026-06-30", amount: 1600, missingIntervalBefore: false },
      { periodEnd: "2026-03-31", amount: 1200, missingIntervalBefore: true }
    ];

    expect(buildCashOnHandSeries(points)).toEqual([
      {
        id: "cash_on_hand_segment_1",
        label: "Cash on hand",
        points: [
          { x: new Date("2026-03-31T00:00:00.000Z"), y: 1200 },
          { x: new Date("2026-06-30T00:00:00.000Z"), y: 1600 }
        ]
      }
    ]);
  });

  it("starts a new singleton segment for each adjacent marked cash-on-hand point", () => {
    const points: CashOnHandPoint[] = [
      { periodEnd: "2026-03-31", amount: 1200, missingIntervalBefore: true },
      { periodEnd: "2026-06-30", amount: 1600, missingIntervalBefore: true }
    ];

    expect(buildCashOnHandSeries(points)).toEqual([
      {
        id: "cash_on_hand_segment_1",
        label: "Cash on hand",
        points: [
          { x: new Date("2026-03-31T00:00:00.000Z"), y: 1200 },
          { x: new Date("2026-04-01T00:00:00.000Z"), y: 1200 }
        ]
      },
      {
        id: "cash_on_hand_segment_2",
        label: "Cash on hand",
        points: [
          { x: new Date("2026-06-30T00:00:00.000Z"), y: 1600 },
          { x: new Date("2026-07-01T00:00:00.000Z"), y: 1600 }
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

  it("budgets band tick label characters from measured plot width, hand-calculated", () => {
    // civibus-tfz. The receipt-composition chart at a 390px viewport: the
    // chart body measures 338px, minus the 56+24px axis gutters leaves a
    // 258px band area over 2 bands. Both bands render a tick
    // (floor(258 / 80) = 3 >= 2), so each label owns 258 / 2 = 129px, and at
    // 6px per character that is a 21-character budget.
    expect(bandTickLabelBudgetChars(258, 2)).toBe(21);

    // Desktop, same chart: 947px body - 80px gutters = 867px over 2 bands ->
    // 433.5px per label -> 72 characters, i.e. no real-world label truncates.
    expect(bandTickLabelBudgetChars(867, 2)).toBe(72);

    // 54 monthly bands at desktop: tickSpacing caps rendered ticks at
    // floor(867 / 80) = 10, so each rendered label owns 86.7px -> 14 chars,
    // comfortably above the 7-character "2026-06" month keys.
    expect(bandTickLabelBudgetChars(867, 54)).toBe(14);

    // The budget never collapses below the readable floor of 8 characters,
    // even in an absurdly narrow plot.
    expect(bandTickLabelBudgetChars(40, 5)).toBe(8);

    // Degenerate inputs mean "no plot to budget": no truncation pressure.
    expect(bandTickLabelBudgetChars(0, 2)).toBe(Number.POSITIVE_INFINITY);
    expect(bandTickLabelBudgetChars(258, 0)).toBe(Number.POSITIVE_INFINITY);

    // The budget arithmetic must stay derived from the same tick spacing the
    // adapter hands layerchart, or the two subsampling models drift apart.
    expect(X_TICK_SPACING_PX).toBe(80);
  });

  it("truncates tick labels to the budget with a single ellipsis", () => {
    expect(truncateTickLabel("Gross individual contributions", 21)).toBe(
      "Gross individual con…"
    );
    expect(truncateTickLabel("PAC/other committee contributions", 21)).toBe(
      "PAC/other committee…"
    );
    // A label at or under budget is untouched — desktop must render full labels.
    expect(truncateTickLabel("In district", 21)).toBe("In district");
    expect(truncateTickLabel("2026-06", 14)).toBe("2026-06");
    // Exactly at budget: untouched.
    expect(truncateTickLabel("abcdefgh", 8)).toBe("abcdefgh");
    // An infinite budget (unmeasured plot) never truncates.
    expect(truncateTickLabel("Gross individual contributions", Number.POSITIVE_INFINITY)).toBe(
      "Gross individual contributions"
    );
  });

  it("keeps support and oppose colors above WCAG contrast thresholds", () => {
    expect(getContrastRatio(FINANCE_CHART_COLORS.support, "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(getContrastRatio(FINANCE_CHART_COLORS.oppose, "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(getContrastRatio(FINANCE_CHART_COLORS.support, "#f8fafc")).toBeGreaterThanOrEqual(3);
    expect(getContrastRatio(FINANCE_CHART_COLORS.oppose, "#f8fafc")).toBeGreaterThanOrEqual(3);
  });
});
