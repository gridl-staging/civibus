export type ChartKind = "line" | "bar";

export type ChartX = string | number | Date;

export interface ChartPoint {
  x: ChartX;
  y: number;
}

export interface ChartSeries {
  id: string;
  label: string;
  points: ChartPoint[];
  /**
   * Explicit series colour. Omitted for the ordinary categorical/sequential case,
   * where `Chart.svelte` assigns from its own palette by series position. Set only
   * where the colour itself is the encoding — a diverging support/oppose scale
   * whose two hues must match the stance colours the surrounding HTML rows already
   * use. See `docs/reference/ui_chart_encoding.md` §1.
   */
  color?: string;
}

/**
 * Document-outline level for a chart's own title heading. Charts are embedded
 * inside sections whose depth varies by page, so the level is a prop rather
 * than a fixed tag: a fixed `<h3>` inside an h4-level section resets the
 * outline mid-section and forces every heading after the chart to h4 or
 * shallower (civibus-4yw). Defaults to 3, preserving pre-prop rendering for
 * every consumer that has not opted in.
 */
export type ChartHeadingLevel = 2 | 3 | 4 | 5 | 6;

export interface ChartProps {
  kind: ChartKind;
  title: string;
  ariaLabel: string;
  /**
   * The unit the enclosing `ChartFrame` declares. Selects the value-axis and
   * tooltip formatters so the plot cannot disagree with the frame's own label.
   */
  unit: FinanceChartUnit;
  series: ChartSeries[];
  yDomain?: [number, number];
  headingLevel?: ChartHeadingLevel;
}

export type FinanceChartUnit = "dollars" | "reported_transactions" | "count" | "percent";

export type ChartSource = {
  label: string;
  href?: string;
};

export type FigureSummary = {
  sentence: string;
};

export type ExactDisclosureValue = {
  label: string;
  value: string;
  href?: string;
};

export type ExactDisclosureRow = {
  label: string;
  values: ExactDisclosureValue[];
};

export type ChartFrameState =
  | { kind: "ready" }
  | { kind: "no-data"; message: string }
  | { kind: "table-only"; message: string };

export type ChartFrameProps = {
  testId: string;
  title: string;
  unit: FinanceChartUnit;
  cycle: number;
  coverageThrough: string | null;
  summary: FigureSummary;
  sources: ChartSource[];
  exactRows: ExactDisclosureRow[];
  state: ChartFrameState;
};

export type ReceiptCompositionRow = {
  id: string;
  label: string;
  amount: number;
  denominator: number;
  canPlot: boolean;
};

export type MonthlyContributionRow = {
  month: string;
  amount: number;
  transactionCount: number;
  covered: boolean;
};

export type CashOnHandPoint = {
  periodEnd: string;
  amount: number;
  missingIntervalBefore: boolean;
};

export type HorizontalBarRow = {
  id: string;
  label: string;
  amount: number;
  transactionCount: number;
  unit: "dollars" | "reported_transactions";
  canPlot: boolean;
};

export type GeographyShareRow = {
  id: string;
  label: string;
  amount: number;
  transactionCount: number;
  denominator: number;
  approximate: boolean;
};

export type OutsideSpendingStance = "support" | "oppose";

export type OutsideSpendingRow = {
  id: string;
  label: string;
  stance: OutsideSpendingStance;
  amount: number;
  transactionCount: number;
  sourceHref?: string;
};
