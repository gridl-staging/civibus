import type {
  CashOnHandPoint,
  ChartPoint,
  ChartSeries,
  ExactDisclosureRow,
  GeographyShareRow,
  MonthlyContributionRow,
  OutsideSpendingRow
} from "./types";

export const FEC_SIZE_BUCKET_LABELS = [
  "$200 and under",
  "$200.01-$499.99",
  "$500-$999.99",
  "$1,000-$1,999.99",
  "$2,000 and over"
] as const;

export const FINANCE_CHART_COLORS = {
  support: "#0f766e",
  oppose: "#92400e",
  neutral: "#334155",
  background: "#ffffff",
  mutedBackground: "#f8fafc"
} as const;

const CURRENCY_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

const COUNT_FORMATTER = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0
});

const MONTH_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "long",
  year: "numeric",
  timeZone: "UTC"
});
const SINGLETON_CASH_SEGMENT_MARKER_DAYS = 1;

export function formatCurrency(value: number): string {
  if (Object.is(value, -0)) {
    return "$0.00";
  }
  return CURRENCY_FORMATTER.format(value);
}

export function formatCurrencyShort(value: number): string {
  if (value >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `$${(value / 1_000).toFixed(0)}K`;
  }
  return `$${value}`;
}

export function formatCount(value: number): string {
  return COUNT_FORMATTER.format(value);
}

export function formatPercent(value: number): string {
  const percent = value * 100;
  const rounded = Math.round(percent * 10) / 10;
  return `${rounded.toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
}

export function formatMonthKey(monthKey: string): string {
  return MONTH_FORMATTER.format(new Date(`${monthKey}-01T00:00:00.000Z`));
}

export function formatDate(value: string | null): string {
  if (!value) {
    return "coverage date unavailable";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC"
  }).format(new Date(`${value}T00:00:00.000Z`));
}

export function orderByUtcMonthKey(rows: MonthlyContributionRow[]): MonthlyContributionRow[] {
  return [...rows].sort((left, right) => left.month.localeCompare(right.month));
}

/**
 */
export function zeroFillCoveredMonths(
  rows: MonthlyContributionRow[],
  coveredMonths: string[]
): MonthlyContributionRow[] {
  const rowsByMonth = new Map(rows.map((row) => [row.month, row]));
  for (const month of coveredMonths) {
    if (!rowsByMonth.has(month)) {
      rowsByMonth.set(month, {
        month,
        amount: 0,
        transactionCount: 0,
        covered: true
      });
    }
  }
  return orderByUtcMonthKey([...rowsByMonth.values()]);
}

export function getReadableTickCeiling(maximumValue: number): number {
  if (maximumValue <= 0) {
    return 0;
  }

  const magnitude = 10 ** Math.floor(Math.log10(maximumValue));
  const normalized = maximumValue / magnitude;
  const step = [1, 1.25, 1.5, 2, 2.5, 5, 10].find((candidate) => normalized <= candidate);
  return (step ?? 10) * magnitude;
}

export function summarizeShare(row: GeographyShareRow): string {
  const share = row.denominator === 0 ? 0 : row.amount / row.denominator;
  return `${row.label} is ${formatCurrency(row.amount)} of ${formatCurrency(row.denominator)} (${formatPercent(share)}).`;
}

/**
 */
export function calculateOutsideSpendingDomain(
  rows: OutsideSpendingRow[],
  sharedScaleMax?: number
): {
  min: number;
  max: number;
  signedRows: Array<{ id: string; label: string; signedAmount: number }>;
} {
  const signedRows = rows.map((row) => ({
    id: row.id,
    label: row.label,
    signedAmount: row.stance === "oppose" ? -Math.abs(row.amount) : Math.abs(row.amount)
  }));
  const values = signedRows.map((row) => row.signedAmount);
  // A shared maximum keeps sibling comparison columns on one zero-centered domain;
  // without one the chart still self-normalizes to its own largest reported value.
  const absoluteMaximum = sharedScaleMax ?? Math.max(0, ...values.map((value) => Math.abs(value)));
  return {
    min: -absoluteMaximum,
    max: absoluteMaximum,
    signedRows
  };
}

/**
 */
export function buildCashOnHandSeries(points: CashOnHandPoint[]): ChartSeries[] {
  const orderedPoints = [...points].sort((left, right) => left.periodEnd.localeCompare(right.periodEnd));
  const segments: CashOnHandPoint[][] = [];

  for (const point of orderedPoints) {
    if (segments.length === 0 || point.missingIntervalBefore) {
      segments.push([point]);
      continue;
    }

    segments.at(-1)?.push(point);
  }

  return segments.map((segment, index) => ({
    id: `cash_on_hand_segment_${index + 1}`,
    label: "Cash on hand",
    points: cashSegmentToChartPoints(segment)
  }));
}

function cashSegmentToChartPoints(segment: CashOnHandPoint[]): ChartPoint[] {
  const points = segment.map((point) => ({
    x: new Date(`${point.periodEnd}T00:00:00.000Z`),
    y: point.amount
  }));

  if (points.length !== 1) {
    return points;
  }

  const [point] = points;
  const markerEnd = new Date(point.x);
  markerEnd.setUTCDate(markerEnd.getUTCDate() + SINGLETON_CASH_SEGMENT_MARKER_DAYS);
  return [point, { x: markerEnd, y: point.y }];
}

export function getContrastRatio(foreground: string, background: string): number {
  const foregroundLuminance = getRelativeLuminance(foreground);
  const backgroundLuminance = getRelativeLuminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 */
export function toExactRows(
  rows: Array<{ label: string; amount: number; transactionCount?: number; denominator?: number }>
): ExactDisclosureRow[] {
  return rows.map((row) => ({
    label: row.label,
    values: [
      { label: "Dollars", value: formatCurrency(row.amount) },
      ...(row.transactionCount === undefined
        ? []
        : [{ label: "Transactions", value: formatCount(row.transactionCount) }]),
      ...(row.denominator === undefined
        ? []
        : [{ label: "Denominator", value: formatCurrency(row.denominator) }])
    ]
  }));
}

function getRelativeLuminance(color: string): number {
  const [red, green, blue] = parseHexColor(color).map((channel) => {
    const normalized = channel / 255;
    if (normalized <= 0.03928) {
      return normalized / 12.92;
    }
    return ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function parseHexColor(color: string): [number, number, number] {
  const normalized = color.replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
    throw new Error(`Expected a 6-digit hex color, received ${color}`);
  }
  return [
    Number.parseInt(normalized.slice(0, 2), 16),
    Number.parseInt(normalized.slice(2, 4), 16),
    Number.parseInt(normalized.slice(4, 6), 16)
  ];
}
