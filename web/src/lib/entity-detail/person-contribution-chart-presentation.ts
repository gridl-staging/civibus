import type {
  PersonContributionInsights,
  ReceiptSourceComponent,
  SerializedMoney
} from "$lib/campaign-finance-detail/contract";
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
  totalReceipts: number;
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

export function parseSerializedMoney(value: SerializedMoney | null | undefined): number {
  if (value === null || value === undefined) {
    return 0;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 */
export function buildPersonReceiptCompositionPresentation(
  summary: ReceiptCompositionSummary
): PersonReceiptCompositionPresentation {
  const totalReceipts = parseSerializedMoney(summary.total_raised);

  return {
    testId: RECEIPT_COMPOSITION_TEST_ID,
    cycle: summary.selected_cycle,
    coverageThrough: summary.coverage_end_date,
    sources: [RECEIPT_SUMMARY_SOURCE],
    totalReceipts,
    canPlot: summary.can_render_share,
    caveat: summary.receipt_source_caveats.join("; "),
    rows: summary.receipt_source_composition.map((component) => ({
      id: buildStableRowId(component.label),
      label: component.label,
      amount: parseSerializedMoney(component.total_amount),
      denominator: totalReceipts,
      canPlot: summary.can_render_share
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
    rows: insights.monthly_totals.map((row) => ({
      month: row.month,
      amount: parseSerializedMoney(row.total_amount),
      transactionCount: row.transaction_count,
      covered: true
    }))
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
    return {
      id: buildStableRowId(label),
      label,
      amount: parseSerializedMoney(bucket?.total_amount),
      transactionCount: bucket?.transaction_count ?? 0,
      canPlot: true
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
  const knownRows = rows.map((row) => ({
    id: buildStableRowId(row.label),
    label: row.label,
    amount: parseSerializedMoney(row.total_amount),
    transactionCount: row.transaction_count,
    denominator,
    approximate
  }));

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
): number {
  const classified = parseSerializedMoney(geography.classified_amount);
  if (geography.geography_mode === "district") {
    return classified + parseSerializedMoney(geography.unknown_amount);
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
  denominator: number
): GeographyShareRow[] {
  if (rows.some((row) => row.label === "Unknown")) {
    return rows;
  }

  const unknownAmount = parseSerializedMoney(insights.geography.unknown_amount);
  const unknownCount = insights.geography.unknown_transaction_count;
  if (insights.geography.geography_mode === "excluded" && unknownAmount === 0 && unknownCount === 0) {
    return rows;
  }

  return [
    ...rows,
    {
      id: "unknown",
      label: "Unknown",
      amount: unknownAmount,
      transactionCount: unknownCount,
      denominator,
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
