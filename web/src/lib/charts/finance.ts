import type {
  CashOnHandPoint,
  ChartPoint,
  ChartSeries,
  ExactDisclosureRow,
  FinanceChartUnit,
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
  // The sign is carried outside the dollar glyph ("-$1.2M", not "$-1.2M") and the
  // magnitude is chosen from the absolute value, because the zero-centered
  // support/oppose chart plots negative dollars and would otherwise emit
  // "$-20000" on every oppose tick.
  const sign = value < 0 ? "-" : "";
  const magnitude = Math.abs(value);

  if (magnitude >= 1_000_000) {
    return `${sign}$${(magnitude / 1_000_000).toFixed(1)}M`;
  }
  if (magnitude >= 1_000) {
    return `${sign}$${(magnitude / 1_000).toFixed(0)}K`;
  }
  return `${sign}$${magnitude}`;
}

export function formatCount(value: number): string {
  return COUNT_FORMATTER.format(value);
}

export function formatPercent(value: number): string {
  const percent = value * 100;
  const rounded = Math.round(percent * 10) / 10;
  return `${rounded.toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
}

/**
 * Value-axis tick formatters keyed by the unit a chart declares on its `ChartFrame`.
 *
 * `docs/reference/ui_chart_encoding.md` §3 owns the rule that a chart's value axis
 * must render in its declared unit; this map is the single implementation of it, so
 * no chart picks a format of its own and none can drift from its declared unit.
 *
 * The dollar entry is deliberately the *abbreviated* formatter. A full-precision
 * `$1,250,000.00` is 14 characters of axis gutter for a number the reader is only
 * using to judge scale, and it was the direct cause of y-axis labels overflowing
 * their own plot by 28-34px in production. Exact cents live in the chart's
 * `View chart data` table and in the hover tooltip below.
 */
export const AXIS_VALUE_FORMATTERS: Record<FinanceChartUnit, (value: number) => string> = {
  dollars: formatCurrencyShort,
  percent: formatPercent,
  count: formatCount,
  reported_transactions: formatCount
};

/**
 * Tooltip value formatters, keyed by the same declared unit.
 *
 * A tooltip is a precision surface — the reader hovered *because* they wanted the
 * number — so money is rendered in full here where the axis abbreviates.
 */
export const TOOLTIP_VALUE_FORMATTERS: Record<FinanceChartUnit, (value: number) => string> = {
  dollars: formatCurrency,
  percent: formatPercent,
  count: formatCount,
  reported_transactions: formatCount
};

/**
 * Minimum horizontal room per x tick label, in CSS pixels. Handed to layerchart
 * as the band axis `tickSpacing`, which is what makes a band axis subsample
 * instead of drawing every category (54 months rendered as 54 overlapping
 * labels before this existed). Owned here beside the label-budget arithmetic
 * below because the two must agree on how many ticks actually render.
 * See docs/reference/ui_chart_encoding.md §5.
 */
export const X_TICK_SPACING_PX = 80;

/**
 * Average width of one axis-tick glyph at the chart's tick font, in CSS pixels.
 * Measured ~5.6px on the CI runner; 6px is deliberately conservative so the
 * budget errs toward truncating one character early rather than letting two
 * neighbouring labels touch. Re-measure alongside AXIS_PADDING if the tick
 * font changes.
 */
const AXIS_TICK_CHAR_WIDTH_PX = 6;

/**
 * A truncated label shorter than this stops being readable at all, so the
 * budget never collapses below it even in an absurdly narrow plot — at that
 * point the full labels in the frame's HTML rows and disclosure table are the
 * readable surface, and the axis only has to stay untangled.
 */
const MIN_TICK_LABEL_CHARS = 8;

/**
 * How many characters one rendered band-axis tick label may spend before it
 * collides with its neighbour (civibus-tfz).
 *
 * Mirrors layerchart's own tick subsampling: `tickSpacing` caps rendered ticks
 * at `floor(bandAreaWidth / X_TICK_SPACING_PX)`, so each rendered label owns
 * `bandAreaWidth / renderedTicks` pixels. Band labels are centred on their
 * band, so two neighbours touch exactly when each label fills its own slot —
 * dividing the slot by a conservative glyph width keeps a visible gap.
 *
 * Degenerate inputs (unmeasured plot, no bands) return Infinity: "no plot to
 * budget" must mean no truncation, never a zero budget that eats every label.
 */
export function bandTickLabelBudgetChars(bandAreaWidthPx: number, bandCount: number): number {
  if (!(bandAreaWidthPx > 0) || !(bandCount > 0)) {
    return Number.POSITIVE_INFINITY;
  }

  const renderedTickCount = Math.max(
    1,
    Math.min(bandCount, Math.floor(bandAreaWidthPx / X_TICK_SPACING_PX))
  );
  const roomPerLabelPx = bandAreaWidthPx / renderedTickCount;
  return Math.max(MIN_TICK_LABEL_CHARS, Math.floor(roomPerLabelPx / AXIS_TICK_CHAR_WIDTH_PX));
}

/**
 * Truncate one tick label to its budget with a single ellipsis. Information is
 * not lost: every chart's frame prints the full label beside its value in the
 * HTML rows and again in the `View chart data` table (civibus-tfz).
 */
export function truncateTickLabel(label: string, maxChars: number): string {
  if (label.length <= maxChars) {
    return label;
  }
  return `${label.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
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
