import type {
  PersonContributionInsights,
  ReceiptSourceComponent,
  SerializedMoney
} from "$lib/campaign-finance-detail/contract";
import {
  compareSerializedMoney,
  formatCurrency,
  sumSerializedMoney
} from "$lib/campaign-finance-detail/presentation";
import { FEC_SIZE_BUCKET_LABELS } from "$lib/charts/finance";
import type {
  ChartSource,
  GeographyShareRow,
  HorizontalBarRow,
  MonthlyContributionRow,
  ReceiptCompositionRow
} from "$lib/charts/types";

const ITEMIZED_SCHEDULE_A_SOURCE: ChartSource = {
  label: "FEC Schedule A itemized individual contributions",
  href: "https://www.fec.gov/data/receipts/individual-contributions/"
};
const RECEIPT_SUMMARY_SOURCE: ChartSource = {
  label: "FEC candidate and committee summaries",
  href: "https://www.fec.gov/data/candidates/"
};
const RECEIPT_COMPOSITION_TEST_ID = "person-receipt-composition";
const MONTHLY_CONTRIBUTIONS_TEST_ID = "person-monthly-contributions";
const SIZE_BUCKETS_TEST_ID = "person-size-buckets";
const GEOGRAPHY_SHARE_TEST_ID = "person-geography-share";
const DISTRICT_APPROXIMATION_NOTE =
  "District geography uses a Census 119th-Congress / 2020-ZCTA approximation.";
// Below 2^45 dollars, a binary64 ULP remains under one cent, so converting
// cents to plot geometry cannot move an exact label to a neighboring cent.
const MAX_SAFE_CHART_MONEY = "35184372088831.99";
const MIN_SAFE_CHART_MONEY = "-35184372088831.99";
export const UNSAFE_CHART_MONEY_MESSAGE =
  "Amounts exceed the safely plottable range; exact values are shown in the chart data table.";

type ChartMoneyProjection = {
  amount: number | null;
  amountLabel: string;
};

type GeographyDenominator = {
  amount: number | null;
  amountLabel: string;
};

type ReceiptCompositionSummary = {
  selected_cycle: number;
  coverage_end_date: string | null;
  total_raised: SerializedMoney;
  receipt_source_composition: ReceiptSourceComponent[];
  can_render_share: boolean;
  receipt_source_caveats: string[];
};

export type PersonReceiptCompositionPresentation = {
  testId: string;
  cycle: number;
  coverageThrough: string | null;
  sources: ChartSource[];
  rows: ReceiptCompositionRow[];
  totalReceipts: number | null;
  canPlot: boolean;
  caveat: string;
};

export type PersonMonthlyContributionsPresentation = {
  testId: string;
  cycle: number;
  coverageThrough: string | null;
  sources: ChartSource[];
  rows: MonthlyContributionRow[];
  coveredMonths: string[];
};

export type PersonSizeBucketPresentation = {
  title: string;
  testId: string;
  cycle: number;
  coverageThrough: string | null;
  sources: ChartSource[];
  rowsByUnit: {
    dollars: HorizontalBarRow[];
    reported_transactions: HorizontalBarRow[];
  };
};

export type PersonGeographySharePresentation = {
  testId: string;
  cycle: number;
  coverageThrough: string | null;
  sources: ChartSource[];
  mode: PersonContributionInsights["geography"]["geography_mode"];
  approximationNote: string;
  rows: GeographyShareRow[];
};

function projectSerializedMoney(
  value: SerializedMoney | null | undefined
): ChartMoneyProjection {
  const serialized = value ?? "0.00";
  const amountLabel = formatCurrency(serialized);
  if (
    compareSerializedMoney(serialized, MIN_SAFE_CHART_MONEY) < 0 ||
    compareSerializedMoney(serialized, MAX_SAFE_CHART_MONEY) > 0
  ) {
    return { amount: null, amountLabel };
  }

  const parsed = Number(serialized);
  return Number.isFinite(parsed)
    ? { amount: parsed, amountLabel }
    : { amount: null, amountLabel };
}

/** Return only a safely plottable numeric projection; never manufacture zero. */
export function parseSerializedMoney(
  value: SerializedMoney | null | undefined
): number | null {
  return projectSerializedMoney(value).amount;
}

/**
 */
export function buildPersonReceiptCompositionPresentation(
  summary: ReceiptCompositionSummary
): PersonReceiptCompositionPresentation {
  const totalReceipts = projectSerializedMoney(summary.total_raised);
  const components = summary.receipt_source_composition.map((component) => ({
    component,
    money: projectSerializedMoney(component.total_amount)
  }));
  const geometryIsSafe =
    totalReceipts.amount !== null && components.every(({ money }) => money.amount !== null);
  const canPlot = summary.can_render_share && geometryIsSafe;
  const caveats = [...summary.receipt_source_caveats];
  if (!geometryIsSafe) {
    caveats.push(UNSAFE_CHART_MONEY_MESSAGE);
  }

  return {
    testId: RECEIPT_COMPOSITION_TEST_ID,
    cycle: summary.selected_cycle,
    coverageThrough: summary.coverage_end_date,
    sources: [RECEIPT_SUMMARY_SOURCE],
    totalReceipts: totalReceipts.amount,
    canPlot,
    caveat: caveats.join("; "),
    rows: components.map(({ component, money }) => ({
      id: buildStableRowId(component.label),
      label: component.label,
      amount: money.amount,
      ...(money.amount === null ? { amountLabel: money.amountLabel } : {}),
      denominator: totalReceipts.amount,
      ...(totalReceipts.amount === null
        ? { denominatorLabel: totalReceipts.amountLabel }
        : {}),
      canPlot
    }))
  };
}

/**
 */
export function buildPersonMonthlyContributionsPresentation(
  insights: PersonContributionInsights
): PersonMonthlyContributionsPresentation {
  return {
    testId: MONTHLY_CONTRIBUTIONS_TEST_ID,
    cycle: insights.metadata.selected_cycle,
    coverageThrough: insights.metadata.coverage_end_date,
    sources: [ITEMIZED_SCHEDULE_A_SOURCE],
    coveredMonths: buildCoveredMonthKeys(
      insights.metadata.coverage_start_date,
      insights.metadata.coverage_end_date
    ),
    rows: insights.monthly_totals.map((row) => {
      const money = projectSerializedMoney(row.total_amount);
      return {
        month: row.month,
        amount: money.amount,
        ...(money.amount === null ? { amountLabel: money.amountLabel } : {}),
        transactionCount: row.transaction_count,
        covered: true
      };
    })
  };
}

/**
 */
export function buildPersonSizeBucketPresentation(
  insights: PersonContributionInsights
): PersonSizeBucketPresentation {
  const bucketsByLabel = new Map(insights.itemized_size_buckets.map((bucket) => [bucket.label, bucket]));
  const baseRows = FEC_SIZE_BUCKET_LABELS.map((label) => {
    const bucket = bucketsByLabel.get(label);
    const money = projectSerializedMoney(bucket?.total_amount);
    return {
      id: buildStableRowId(label),
      label,
      amount: money.amount,
      ...(money.amount === null ? { amountLabel: money.amountLabel } : {}),
      transactionCount: bucket?.transaction_count ?? 0,
      canPlot: money.amount !== null
    };
  });

  return {
    title: "Itemized contribution-size buckets",
    testId: SIZE_BUCKETS_TEST_ID,
    cycle: insights.metadata.selected_cycle,
    coverageThrough: insights.metadata.coverage_end_date,
    sources: [ITEMIZED_SCHEDULE_A_SOURCE],
    rowsByUnit: {
      dollars: baseRows.map((row) => ({ ...row, unit: "dollars" })),
      reported_transactions: baseRows.map((row) => ({ ...row, unit: "reported_transactions" }))
    }
  };
}

/**
 */
export function buildPersonGeographySharePresentation(
  insights: PersonContributionInsights
): PersonGeographySharePresentation {
  const geography = insights.geography;
  const rows = geography.geography_mode === "district" ? geography.by_district : geography.by_state;
  const denominator = computeGeographyVisibleDenominator(geography);
  const approximate = geography.geography_mode === "district" && insights.metadata.approximate_geography;
  const knownRows = rows.map((row) => {
    const money = projectSerializedMoney(row.total_amount);
    return {
      id: buildStableRowId(row.label),
      label: row.label,
      amount: money.amount,
      ...(money.amount === null ? { amountLabel: money.amountLabel } : {}),
      transactionCount: row.transaction_count,
      denominator: denominator.amount,
      ...(denominator.amount === null
        ? { denominatorLabel: denominator.amountLabel }
        : {}),
      approximate
    };
  });

  return {
    testId: GEOGRAPHY_SHARE_TEST_ID,
    cycle: insights.metadata.selected_cycle,
    coverageThrough: insights.metadata.coverage_end_date,
    sources: [ITEMIZED_SCHEDULE_A_SOURCE],
    mode: geography.geography_mode,
    approximationNote: approximate ? DISTRICT_APPROXIMATION_NOTE : "",
    rows: appendUnknownGeographyRow(knownRows, insights, denominator)
  };
}

/**
 * Resolve the single denominator every displayed geography bar shares. District
 * geography is a complete in/out/Unknown partition, so the Unknown bar draws
 * from the same base and the denominator must include `unknown_amount`.
 * Per-state modes show shares of the classified (state-attributed) base only.
 */
function computeGeographyVisibleDenominator(
  geography: PersonContributionInsights["geography"]
): GeographyDenominator {
  const classified = projectSerializedMoney(geography.classified_amount);
  if (geography.geography_mode === "district") {
    return projectSerializedMoney(
      sumSerializedMoney([geography.classified_amount, geography.unknown_amount])
    );
  }
  return classified;
}

/**
 * Append the synthesized Unknown geography row when one is not already present,
 * reusing the shared visible denominator so its share is consistent with the
 * classified rows.
 */
function appendUnknownGeographyRow(
  rows: GeographyShareRow[],
  insights: PersonContributionInsights,
  denominator: GeographyDenominator
): GeographyShareRow[] {
  if (rows.some((row) => row.label === "Unknown")) {
    return rows;
  }

  const unknownAmount = projectSerializedMoney(insights.geography.unknown_amount);
  const unknownCount = insights.geography.unknown_transaction_count;
  if (
    insights.geography.geography_mode === "excluded" &&
    compareSerializedMoney(insights.geography.unknown_amount, "0") === 0 &&
    unknownCount === 0
  ) {
    return rows;
  }

  return [
    ...rows,
    {
      id: "unknown",
      label: "Unknown",
      amount: unknownAmount.amount,
      ...(unknownAmount.amount === null
        ? { amountLabel: unknownAmount.amountLabel }
        : {}),
      transactionCount: unknownCount,
      denominator: denominator.amount,
      ...(denominator.amount === null
        ? { denominatorLabel: denominator.amountLabel }
        : {}),
      approximate: insights.geography.geography_mode === "district"
    }
  ];
}

/**
 */
function buildCoveredMonthKeys(startDate: string, endDate: string): string[] {
  const start = parseMonthStart(startDate);
  const end = parseMonthStart(endDate);
  if (start === null || end === null || start > end) {
    return [];
  }

  const months: string[] = [];
  for (
    let year = start.year, month = start.month;
    year < end.year || (year === end.year && month <= end.month);
    month += 1
  ) {
    if (month > 12) {
      year += 1;
      month = 1;
    }
    months.push(`${year}-${String(month).padStart(2, "0")}`);
  }
  return months;
}

function parseMonthStart(value: string): { year: number; month: number } | null {
  const match = /^(\d{4})-(\d{2})-\d{2}$/.exec(value);
  if (match === null) {
    return null;
  }

  return {
    year: Number(match[1]),
    month: Number(match[2])
  };
}

function buildStableRowId(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}
