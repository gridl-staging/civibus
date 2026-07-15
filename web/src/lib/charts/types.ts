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
}

export interface ChartProps {
  kind: ChartKind;
  title: string;
  ariaLabel: string;
  series: ChartSeries[];
  yDomain?: [number, number];
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
