import type {
  CandidateFundraisingSummary,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary,
  SerializedMoney
} from "$lib/campaign-finance-detail/contract";
import { formatCurrency, type OutsideSpendingPresentation } from "$lib/campaign-finance-detail/presentation";
import type { OutsideSpendingRow } from "$lib/charts/types";
import type { SourceInfo } from "$lib/entity-detail/contract";
import {
  buildPersonContributionInsightsPresentation,
  buildPersonMoneyAtGlancePresentation,
  buildPersonMoneyAtGlanceSummary,
  buildPersonOutsideSpendingSection,
  type PersonContributionInsightsPresentation,
  type PersonMoneyAtGlancePresentation,
  type PersonMoneyAtGlanceSummary
} from "$lib/entity-detail/person-campaign-finance-presentation";
import { parseSerializedMoney } from "$lib/entity-detail/person-contribution-chart-presentation";
import type { CompareColumn, ResolvedPersonMoneyBundle } from "./+page.server";

type CompareMetricUnit = "money" | "percent";
type CompareColumnStatus = "ready" | "error";
type CompareCellState = "available" | "unavailable";

type CompareMetricValue = {
  value: number | null;
  label: string;
  state: CompareCellState;
};

export type ComparePresentationColumn = {
  personId: string;
  name: string;
  href: string;
  status: CompareColumnStatus;
  errorMessage: string | null;
  provenanceLinks: CompareProvenanceLink[];
};

export type CompareProvenanceLink = {
  label: string;
  href: string;
};

export type CompareMetricCell = CompareMetricValue & {
  personId: string;
};

export type CompareMetricRow = {
  id: string;
  label: string;
  unit: CompareMetricUnit;
  scaleMax: number;
  scaleMaxLabel: string;
  cells: CompareMetricCell[];
};

export type CompareChartScale = {
  max: number;
  maxLabel: string;
};

/**
 * One shared domain per chart row, so a column that raised $5M and a column that
 * raised $50K plot against the same maximum instead of each self-normalizing to
 * full width. Geography rows are omitted: they already render as shares of each
 * column's own denominator, which is comparable without a shared money domain.
 */
export type CompareChartScales = {
  monthlyContributions: CompareChartScale;
  sizeBucketDollars: CompareChartScale;
  outsideSpending: CompareChartScale;
};

export type CompareColumnCharts = {
  personId: string;
  moneyAtGlance: PersonMoneyAtGlancePresentation | null;
  contributionInsights: PersonContributionInsightsPresentation | null;
  outsideSpending: CompareOutsideSpendingChart | null;
};

export type CompareOutsideSpendingChart = {
  cycle: number;
  coverageThrough: string | null;
  rows: OutsideSpendingRow[];
  topSpenders: OutsideSpendingRow[];
};

type FulfilledColumnPresentation = {
  summary: PersonMoneyAtGlanceSummary | null;
  moneyAtGlance: PersonMoneyAtGlancePresentation | null;
  contributionInsights: PersonContributionInsightsPresentation;
  outsideSpending: CompareOutsideSpendingChart | null;
  outsideSupport: number | null;
  outsideOppose: number | null;
};

type ColumnPresentationResult =
  | { status: "fulfilled"; value: FulfilledColumnPresentation }
  | { status: "rejected"; reason: unknown };

export type ComparePresentation = {
  columns: ComparePresentationColumn[];
  rows: CompareMetricRow[];
  charts: CompareColumnCharts[];
  chartScales: CompareChartScales;
  answerFirstSummary: string;
  dataThroughLabel: string;
  fairnessCopy: string;
  provenanceCopy: string;
};

const UNAVAILABLE_VALUE: CompareMetricValue = {
  value: null,
  label: "Not available",
  state: "unavailable"
};

const FAIRNESS_COPY =
  "Compare each officeholder within that person's selected cycle, using official FEC summaries when available and itemized records where summaries are not yet loaded.";
const PROVENANCE_COPY =
  "Campaign finance data comes from the Federal Election Commission; entity details link to their source records when available.";

function fulfilledOutcome<T>(
  outcome: PromiseSettledResult<T>
): outcome is PromiseFulfilledResult<T> {
  return outcome.status === "fulfilled";
}

function isCandidateSummary(value: CandidateFundraisingSummary | null): value is CandidateFundraisingSummary {
  return value !== null;
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function moneyValue(value: SerializedMoney | null | undefined): CompareMetricValue {
  if (value === null || value === undefined) {
    return UNAVAILABLE_VALUE;
  }

  return {
    value: parseSerializedMoney(value),
    label: formatCurrency(value),
    state: "available"
  };
}

function percentValue(value: number | null): CompareMetricValue {
  if (value === null || !Number.isFinite(value)) {
    return UNAVAILABLE_VALUE;
  }

  return {
    value,
    label: formatPercent(value),
    state: "available"
  };
}

function buildPersonHref(personId: string): string {
  return `/person/${encodeURIComponent(personId)}`;
}

function buildProvenanceLinks(sources: SourceInfo[]): CompareProvenanceLink[] {
  return sources.flatMap((source) => {
    const href = source.record_url ?? source.data_source_url;
    if (href === null) {
      return [];
    }
    return [{ label: source.data_source_name, href }];
  });
}

function prefixOutsideSpendingRows(
  candidateId: string,
  rows: OutsideSpendingRow[]
): OutsideSpendingRow[] {
  return rows.map((row) => ({
    ...row,
    id: `${candidateId}-${row.id}`
  }));
}

/**
 */
function buildOutsideSpendingChart(
  sections: ResolvedPersonMoneyBundle["personFinanceSections"],
  presentations: OutsideSpendingPresentation[]
): CompareOutsideSpendingChart | null {
  const summaryFacts = sections.flatMap((section) =>
    section.ieSummary === null ? [] : [section.ieSummary]
  );
  if (summaryFacts.length === 0) {
    return null;
  }
  const latestSummary = getLatestOutsideSpendingSummary(summaryFacts);

  return {
    cycle: latestSummary.selected_cycle,
    coverageThrough: latestSummary.coverage_end_date,
    rows: presentations.flatMap((presentation, index) =>
      prefixOutsideSpendingRows(sections[index].candidate.id, presentation.chartRows)
    ),
    topSpenders: presentations.flatMap((presentation, index) =>
      prefixOutsideSpendingRows(sections[index].candidate.id, presentation.chartTopSpenders)
    )
  };
}

function getLatestOutsideSpendingSummary(
  summaries: IndependentExpenditureSummary[]
): IndependentExpenditureSummary {
  return summaries.reduce((latest, current) =>
    current.coverage_end_date > latest.coverage_end_date ? current : latest
  );
}

async function resolveCandidateSummary(
  summary: Promise<CandidateFundraisingSummary>
): Promise<CandidateFundraisingSummary | null> {
  const value = await summary;
  return value ?? null;
}

/**
 */
async function resolveColumnPresentation(
  bundle: ResolvedPersonMoneyBundle
): Promise<FulfilledColumnPresentation> {
  const summaryResults = await Promise.allSettled(
    bundle.personFinanceSections.map((section) => resolveCandidateSummary(section.summary))
  );
  const summaries = summaryResults.filter(fulfilledOutcome).map((result) => result.value);
  const allSummariesAvailable = summaries.length === bundle.personFinanceSections.length;
  const completeSummaries = summaries.filter(isCandidateSummary);
  const summary =
    allSummariesAvailable && completeSummaries.length === summaries.length && completeSummaries.length > 0
      ? buildPersonMoneyAtGlanceSummary(completeSummaries)
      : null;

  const outsideSpending = await Promise.all(
    bundle.personFinanceSections.map(async (section) =>
      buildPersonOutsideSpendingSection(
        section.ieSummary,
        (await section.ieTransactions) as IndependentExpenditureResponse[]
      )
    )
  );
  const contributionInsights = buildPersonContributionInsightsPresentation(
    bundle.personContributionInsights,
    bundle.personTopDonors,
    bundle.personTopEmployers
  );

  return {
    summary,
    moneyAtGlance: summary === null ? null : buildPersonMoneyAtGlancePresentation(summary),
    contributionInsights,
    outsideSpending: buildOutsideSpendingChart(bundle.personFinanceSections, outsideSpending),
    outsideSupport: sumOutsideSpending(outsideSpending.map((section) => section.chartRows), "support"),
    outsideOppose: sumOutsideSpending(outsideSpending.map((section) => section.chartRows), "oppose")
  };
}

function sumOutsideSpending(
  rowsBySection: OutsideSpendingRow[][],
  stance: "support" | "oppose"
): number | null {
  const rows = rowsBySection.flat().filter((row) => row.stance === stance);
  if (rows.length === 0) {
    return null;
  }
  return rows.reduce((total, row) => total + row.amount, 0);
}

function buildSelfFundingShare(summary: PersonMoneyAtGlanceSummary | null): CompareMetricValue {
  if (summary === null || summary.net_self_funding === null) {
    return UNAVAILABLE_VALUE;
  }

  const totalRaised = parseSerializedMoney(summary.total_raised);
  if (totalRaised <= 0) {
    return UNAVAILABLE_VALUE;
  }

  return percentValue(parseSerializedMoney(summary.net_self_funding) / totalRaised);
}

function buildSmallDollarShare(
  result: ColumnPresentationResult,
  bundle: ResolvedPersonMoneyBundle | null
): CompareMetricValue {
  if (result.status === "rejected" || bundle === null) {
    return UNAVAILABLE_VALUE;
  }

  const share = bundle.personContributionInsights.small_dollar_share.share;
  return share === null ? UNAVAILABLE_VALUE : percentValue(Number(share));
}

function maxReportedValue(values: readonly number[]): number {
  const reported = values.filter((value) => Number.isFinite(value));
  return reported.length === 0 ? 0 : Math.max(...reported);
}

function scaleMaxFor(cells: CompareMetricCell[]): number {
  return maxReportedValue(
    cells.flatMap((cell) => (cell.state === "available" && cell.value !== null ? [cell.value] : []))
  );
}

function buildChartScale(values: readonly number[]): CompareChartScale {
  const max = maxReportedValue(values);
  return { max, maxLabel: formatScaleMax(max, "money") };
}

/**
 * Derives each chart row's shared domain from the same presentation rows the
 * columns render, so the stated caption and the plotted bars can never diverge.
 * Rejected columns contribute no values rather than a zero.
 */
function buildChartScales(charts: readonly CompareColumnCharts[]): CompareChartScales {
  return {
    monthlyContributions: buildChartScale(
      charts.flatMap((chart) =>
        (chart.contributionInsights?.monthlyContributions.rows ?? []).map((row) => row.amount)
      )
    ),
    sizeBucketDollars: buildChartScale(
      charts.flatMap((chart) =>
        (chart.contributionInsights?.sizeBuckets.rowsByUnit.dollars ?? [])
          .filter((row) => row.canPlot)
          .map((row) => row.amount)
      )
    ),
    outsideSpending: buildChartScale(
      charts.flatMap((chart) => (chart.outsideSpending?.rows ?? []).map((row) => Math.abs(row.amount)))
    )
  };
}

function formatScaleMax(value: number, unit: CompareMetricUnit): string {
  return unit === "money" ? formatCurrency(value) : formatPercent(value);
}

/**
 */
function buildRow(
  id: string,
  label: string,
  unit: CompareMetricUnit,
  columns: readonly CompareColumn[],
  values: readonly CompareMetricValue[]
): CompareMetricRow {
  const cells = columns.map((column, index) => ({
    personId: column.personId,
    ...values[index]
  }));
  const scaleMax = scaleMaxFor(cells);
  return {
    id,
    label,
    unit,
    scaleMax,
    scaleMaxLabel: formatScaleMax(scaleMax, unit),
    cells
  };
}

/**
 */
function buildRows(
  columns: readonly CompareColumn[],
  resolved: readonly ColumnPresentationResult[],
  bundles: readonly (ResolvedPersonMoneyBundle | null)[]
): CompareMetricRow[] {
  const summaries = resolved.map((result) =>
    result.status === "fulfilled" ? result.value.summary : null
  );

  return [
    buildRow("total-raised", "Total receipts", "money", columns, summaries.map((summary) => moneyValue(summary?.total_raised))),
    buildRow("total-spent", "Total disbursements", "money", columns, summaries.map((summary) => moneyValue(summary?.total_spent))),
    buildRow("cash-on-hand", "Cash on hand", "money", columns, summaries.map((summary) => moneyValue(summary?.cash_on_hand))),
    buildRow(
      "ie-support",
      "Outside spending supporting",
      "money",
      columns,
      resolved.map((result) =>
        result.status === "fulfilled" && result.value.outsideSupport !== null
          ? { value: result.value.outsideSupport, label: formatCurrency(result.value.outsideSupport), state: "available" }
          : UNAVAILABLE_VALUE
      )
    ),
    buildRow(
      "ie-oppose",
      "Outside spending opposing",
      "money",
      columns,
      resolved.map((result) =>
        result.status === "fulfilled" && result.value.outsideOppose !== null
          ? { value: result.value.outsideOppose, label: formatCurrency(result.value.outsideOppose), state: "available" }
          : UNAVAILABLE_VALUE
      )
    ),
    buildRow(
      "small-dollar-share",
      "Small-dollar share",
      "percent",
      columns,
      resolved.map((result, index) => buildSmallDollarShare(result, bundles[index]))
    ),
    buildRow(
      "self-funded-share",
      "Self-funded share",
      "percent",
      columns,
      summaries.map(buildSelfFundingShare)
    )
  ];
}

/**
 */
function buildAnswerFirstSummary(
  columns: readonly ComparePresentationColumn[],
  rows: readonly CompareMetricRow[]
): string {
  const raisedRow = rows.find((row) => row.id === "total-raised");
  const supportRow = rows.find((row) => row.id === "ie-support");
  const raisedLeader = findLeader(columns, raisedRow);
  const supportLeader = findLeader(columns, supportRow);

  if (raisedLeader === null && supportLeader === null) {
    return "No comparable campaign-finance totals are available yet.";
  }

  const parts = [];
  if (raisedLeader !== null) {
    parts.push(`${raisedLeader.name} has the most total receipts at ${raisedLeader.label}`);
  }
  if (supportLeader !== null) {
    parts.push(`${supportLeader.name} has the most outside support at ${supportLeader.label}`);
  }
  return `${parts.join("; ")}.`;
}

function findLeader(
  columns: readonly ComparePresentationColumn[],
  row: CompareMetricRow | undefined
): { name: string; label: string } | null {
  if (row === undefined) {
    return null;
  }

  const ranked = row.cells
    .map((cell, index) => ({ cell, column: columns[index] }))
    .filter(({ cell }) => cell.state === "available" && cell.value !== null)
    .sort((left, right) => (right.cell.value ?? 0) - (left.cell.value ?? 0));
  const leader = ranked[0];
  return leader === undefined ? null : { name: leader.column.name, label: leader.cell.label };
}

function buildDataThroughLabel(results: readonly ColumnPresentationResult[]): string {
  const dates = results.flatMap((result) =>
    result.status === "fulfilled" && result.value.summary !== null
      ? [result.value.summary.coverage_end_date]
      : []
  );
  if (dates.length === 0) {
    return "Data through not available";
  }
  return `Data through ${dates.sort().at(-1)}`;
}

/**
 */
export async function buildComparePresentation(
  columns: readonly CompareColumn[],
  outcomes: readonly PromiseSettledResult<ResolvedPersonMoneyBundle>[]
): Promise<ComparePresentation> {
  const resolved = await Promise.all(
    outcomes.map(async (outcome): Promise<ColumnPresentationResult> => {
      if (outcome.status === "rejected") {
        return { status: "rejected", reason: outcome.reason };
      }
      try {
        return { status: "fulfilled", value: await resolveColumnPresentation(outcome.value) };
      } catch (reason) {
        return { status: "rejected", reason };
      }
    })
  );
  const bundles = outcomes.map((outcome) => (outcome.status === "fulfilled" ? outcome.value : null));
  const presentationColumns = columns.map((column, index) => ({
    personId: column.personId,
    name: column.person.detail.canonical_name,
    href: buildPersonHref(column.personId),
    status: resolved[index].status === "fulfilled" ? "ready" as const : "error" as const,
    errorMessage:
      resolved[index].status === "rejected" ? "Campaign finance data is unavailable for this person." : null,
    provenanceLinks: buildProvenanceLinks(column.person.detail.sources)
  }));
  const rows = buildRows(columns, resolved, bundles);
  const charts = resolved.map((result, index) => ({
    personId: columns[index].personId,
    moneyAtGlance: result.status === "fulfilled" ? result.value.moneyAtGlance : null,
    contributionInsights: result.status === "fulfilled" ? result.value.contributionInsights : null,
    outsideSpending: result.status === "fulfilled" ? result.value.outsideSpending : null
  }));

  return {
    columns: presentationColumns,
    rows,
    charts,
    chartScales: buildChartScales(charts),
    answerFirstSummary: buildAnswerFirstSummary(presentationColumns, rows),
    dataThroughLabel: buildDataThroughLabel(resolved),
    fairnessCopy: FAIRNESS_COPY,
    provenanceCopy: PROVENANCE_COPY
  };
}
