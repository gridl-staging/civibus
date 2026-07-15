import {
  buildCandidateDeferredOutsideSpending,
  buildCandidateCommitteeBreakdown,
  buildCommitteeDeferredTransactionRows,
  buildRankedPartyRows,
  formatCurrency,
  type CandidateCommitteeBreakdownRow,
  type CommitteeTransactionRow,
  type OutsideSpendingPresentation,
  type RankedPartyRow
} from "$lib/campaign-finance-detail/presentation";
import type {
  CandidateFundraisingSummary,
  CampaignFinanceTransactionResponse,
  ContributionInsightsCareerTotals,
  ContributionInsightsCycleTotal,
  ContributionInsightsDistrictShare,
  ContributionInsightsTotalsSource,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary,
  PersonContributionInsights,
  PersonTopEmployerRow,
  RankedTransactionParty,
  ReceiptSourceComponent,
  SerializedMoney
} from "$lib/campaign-finance-detail/contract";
import type { ChartSeries } from "$lib/charts/types";
import { formatCountLabel } from "$lib/count-label";
import {
  buildPersonGeographySharePresentation,
  buildPersonMonthlyContributionsPresentation,
  buildPersonReceiptCompositionPresentation,
  buildPersonSizeBucketPresentation,
  parseSerializedMoney,
  type PersonGeographySharePresentation,
  type PersonMonthlyContributionsPresentation,
  type PersonReceiptCompositionPresentation,
  type PersonSizeBucketPresentation
} from "./person-contribution-chart-presentation";
import {
  buildDonorVendorEmptyStateBanner,
  buildLinkedCommitteeEmptyStateBanner
} from "$lib/detail-trust/presentation";

type PersonMoneyMetricRow = {
  label: string;
  value: string;
};

type PersonRankedPartyRow = RankedPartyRow & {
  barPercent: number;
};

/**
 */
export type PersonContributionInsightsPresentation = {
  emptyMessage: string | null;
  caveatMessages: string[];
  coverageLabel: string;
  topDonors: PersonRankedPartyRow[];
  topDonorsEmptyMessage: string | null;
  topEmployers: PersonRankedPartyRow[];
  topEmployersEmptyMessage: string | null;
  topEmployerDisclaimer: string;
  topEmployerMethodologyReference: string;
  rankingLabels: {
    topDonors: string;
    topEmployers: string;
  };
  totalSummaryViews: PersonContributionTotalSummaryView[];
  defaultTotalSummaryKey: PersonContributionTotalSummaryKey | null;
  totalsEmptyMessage: string | null;
  smallDollarHeadline: string;
  smallDollarSummary: string;
  districtShareHeadline: string;
  districtShareSummary: string;
  monthlyContributions: PersonMonthlyContributionsPresentation;
  sizeBuckets: PersonSizeBucketPresentation;
  geographyShare: PersonGeographySharePresentation;
  unitemizedExclusionNote: string;
  geographyNote: string;
};

export type PersonContributionTotalSummaryKey = "cycle" | "career";

export type PersonContributionTotalSummaryView = {
  key: PersonContributionTotalSummaryKey;
  label: string;
  amountLabel: string;
  itemizedAmountLabel: string;
  unitemizedAmountLabel: string;
  transactionCountLabel: string;
  caveatMessage: string | null;
};

export type PersonCycleOption = {
  cycle: number;
  label: string;
  href: string;
  selected: boolean;
};

export type PersonMoneyAtGlancePresentation = {
  heading: string;
  cycleLabel: string;
  coverageLabel: string;
  sourceLabel: string;
  cycleOptions: PersonCycleOption[];
  metricRows: PersonMoneyMetricRow[];
  receiptComposition: PersonReceiptCompositionPresentation;
};

type PersonMoneySummarySource = CandidateFundraisingSummary["summary_source"] | "mixed";
type PersonMoneyField = "total_raised" | "total_spent" | "net";
type PersonMoneyCountField = "transaction_count" | "itemized_transaction_count";

export type PersonMoneyAtGlanceSummary = Omit<
  CandidateFundraisingSummary,
  "summary_source"
> & {
  summary_source: PersonMoneySummarySource;
};

const DEFAULT_UNITEMIZED_EXCLUSION_NOTE =
  "Unitemized contributions are excluded from count and geography charts.";
const SMALL_DOLLAR_UNAVAILABLE_SUMMARY = "Committee summary totals are not available yet.";
const PERSON_TOP_DONORS_EMPTY_MESSAGE = "No donor rankings available.";
const PERSON_TOP_EMPLOYERS_EMPTY_MESSAGE = "No employer rankings available.";
const PERSON_TOP_EMPLOYER_DISCLAIMER =
  "Top employers aggregate raw employer names from itemized individual contributions only.";
const PERSON_TOP_EMPLOYER_METHODOLOGY_REFERENCE =
  "They are not industry- or sector-coded; see Methodology for source-linking and evidence limitations.";
const PERSON_TOTALS_EMPTY_MESSAGE = "No itemized individual-contribution totals are available yet.";
const DISTRICT_SHARE_UNAVAILABLE_HEADLINE = "District share unavailable";
const DISTRICT_SHARE_UNAVAILABLE_SUMMARY =
  "District-share geography is unavailable until in-district and out-of-district itemized totals are available.";
const ITEMIZED_TOTALS_CAVEAT =
  "Only itemized individual contributions are included; unitemized totals are unavailable for this view.";
const MIXED_TOTALS_CAVEAT =
  "Totals combine itemized transactions with available committee-summary data; unitemized coverage may be incomplete.";
const APPROXIMATE_DISTRICT_GEOGRAPHY_NOTE =
  "District geography uses a Census 119th-Congress / 2020-ZCTA approximation.";
const STATE_GEOGRAPHY_NOTE = "Contributor geography by state.";
const CONTRIBUTION_INSIGHTS_EMPTY_MESSAGES: Record<string, string> = {
  missing_committee_summary:
    "Committee summary totals are required before dollars by size can be shown.",
  missing_zcta_district:
    "District geography is unavailable until ZCTA district reference data is loaded."
};
const CONTRIBUTION_INSIGHTS_LOADED_CAVEAT_MESSAGES: Record<string, string> = {
  missing_committee_summary:
    "Committee summary totals are unavailable, so summary-backed unitemized dollars are not included.",
  itemized_summary_reconciliation_unavailable:
    "Itemized totals cannot be reconciled to committee summary totals, so this view uses itemized-only contribution facts.",
  itemized_summary_reconciliation_mismatch:
    "Itemized totals do not match committee summary totals, so this view uses itemized-only contribution facts."
};
const CONTRIBUTION_INSIGHTS_EXCLUDED_GEOGRAPHY_MESSAGES: Record<string, string> = {
  no_linked_candidate: "No linked candidate is available for fundraising detail.",
  statewide_office: "Statewide offices use state-level fundraising geography.",
  federal_executive: "Federal executive offices use national fundraising geography.",
  no_current_federal_officeholding:
    "District geography is unavailable until a current federal officeholding is linked.",
  missing_member_district:
    "District geography is unavailable until the linked federal office has a state and district."
};

const PERSON_SUMMARY_SOURCE_LABELS: Record<PersonMoneySummarySource, string> = {
  fec_weball: "Official FEC candidate summary",
  derived: "Derived from itemized transactions",
  mixed: "Mixed official FEC and derived summary data"
};

function parseMoney(value: SerializedMoney): number {
  return parseSerializedMoney(value);
}

function formatCoverageLabel(startDate: string, endDate: string | null): string {
  return endDate === null ? `from ${startDate}` : `${startDate} to ${endDate}`;
}

function formatSharePercent(value: SerializedMoney | null): string {
  if (value === null) {
    return "Small-dollar share unavailable";
  }

  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "Small-dollar share unavailable";
  }

  return `${Math.round(parsed * 100)}%`;
}

function buildSingleSeries(
  id: string,
  label: string,
  points: { x: string; y: number }[]
): ChartSeries[] {
  return [{ id, label, points }];
}

/**
 */
function resolveContributionInsightsEmptyMessage(insights: PersonContributionInsights): string | null {
  if (insights.has_data) {
    return null;
  }

  const excludedGeographyMessage = resolveExcludedGeographyMessage(insights);
  if (excludedGeographyMessage !== null) {
    return excludedGeographyMessage;
  }

  for (const caveat of insights.metadata.caveats) {
    const message = CONTRIBUTION_INSIGHTS_EMPTY_MESSAGES[caveat];
    if (message !== undefined) {
      return message;
    }
  }

  return "Itemized contribution rows are not loaded yet.";
}

function resolveContributionInsightsCaveatMessages(insights: PersonContributionInsights): string[] {
  if (!insights.has_data) {
    return [];
  }

  return insights.metadata.caveats.flatMap((caveat) => {
    const message = CONTRIBUTION_INSIGHTS_LOADED_CAVEAT_MESSAGES[caveat];
    return message === undefined ? [] : [message];
  });
}

function resolveExcludedGeographyMessage(insights: PersonContributionInsights): string | null {
  const excludedGeography = insights.metadata.excluded_geography;
  if (excludedGeography === null) {
    return null;
  }

  return CONTRIBUTION_INSIGHTS_EXCLUDED_GEOGRAPHY_MESSAGES[excludedGeography] ?? null;
}

/**
 */
function resolveContributionInsightsGeographyNote(
  insights: PersonContributionInsights,
  hasDistrictGeography: boolean
): string {
  const excludedGeographyMessage = resolveExcludedGeographyMessage(insights);
  if (
    excludedGeographyMessage !== null &&
    insights.metadata.excluded_geography !== "no_linked_candidate"
  ) {
    return excludedGeographyMessage;
  }

  if (!hasDistrictGeography && insights.metadata.caveats.includes("missing_zcta_district")) {
    return CONTRIBUTION_INSIGHTS_EMPTY_MESSAGES.missing_zcta_district;
  }

  if (hasDistrictGeography && insights.metadata.approximate_geography) {
    return APPROXIMATE_DISTRICT_GEOGRAPHY_NOTE;
  }

  return STATE_GEOGRAPHY_NOTE;
}

function buildSmallDollarSummary(insights: PersonContributionInsights): string {
  const share = insights.small_dollar_share;
  if (
    !share.available ||
    share.small_dollar_amount === null ||
    share.total_contribution_amount === null
  ) {
    return SMALL_DOLLAR_UNAVAILABLE_SUMMARY;
  }

  return `${formatCurrency(share.small_dollar_amount)} of ${formatCurrency(
    share.total_contribution_amount
  )} from small-dollar sources`;
}

function formatDistrictShareHeadline(share: SerializedMoney | null): string {
  if (share === null) {
    return DISTRICT_SHARE_UNAVAILABLE_HEADLINE;
  }

  const parsed = Number(share);
  if (!Number.isFinite(parsed)) {
    return DISTRICT_SHARE_UNAVAILABLE_HEADLINE;
  }

  return `${Math.round(parsed * 100)}% in district`;
}

/**
 */
function buildDistrictShareSummary(districtShare: ContributionInsightsDistrictShare): string {
  if (
    !districtShare.available ||
    districtShare.in_district_amount === null ||
    districtShare.out_of_district_amount === null
  ) {
    return DISTRICT_SHARE_UNAVAILABLE_SUMMARY;
  }

  const baseSummary = `${formatCurrency(districtShare.in_district_amount)} in district and ${formatCurrency(
    districtShare.out_of_district_amount
  )} out of district`;
  if (
    districtShare.unknown_district_amount === null ||
    parseMoney(districtShare.unknown_district_amount) === 0
  ) {
    return `${baseSummary}.`;
  }

  return `${baseSummary}; ${formatCurrency(
    districtShare.unknown_district_amount
  )} unknown district excluded from the share.`;
}

function buildRankedRowsWithBars(
  rows: { name: string; total_amount: SerializedMoney; transaction_count: number }[]
): PersonRankedPartyRow[] {
  const maxAmount = Math.max(0, ...rows.map((row) => Math.abs(parseMoney(row.total_amount))));
  return buildRankedPartyRows(rows).map((row, index) => ({
    ...row,
    barPercent: maxAmount === 0 ? 0 : Math.round((Math.abs(parseMoney(rows[index].total_amount)) / maxAmount) * 100)
  }));
}

function buildTopEmployerRowsWithBars(
  personTopEmployers: PersonTopEmployerRow[]
): PersonRankedPartyRow[] {
  return buildRankedRowsWithBars(
    personTopEmployers.map((row) => ({
      name: row.employer,
      total_amount: row.total_amount,
      transaction_count: row.transaction_count
    }))
  );
}

function resolveTotalsCaveat(source: ContributionInsightsTotalsSource): string | null {
  if (source === "itemized_transactions") {
    return ITEMIZED_TOTALS_CAVEAT;
  }

  if (source === "mixed_sources") {
    return MIXED_TOTALS_CAVEAT;
  }

  return null;
}

function hasContributionTotals(source: ContributionInsightsTotalsSource): boolean {
  return source !== "none";
}

/**
 */
function buildTotalSummaryView(
  key: PersonContributionTotalSummaryKey,
  label: string,
  totals: ContributionInsightsCycleTotal | ContributionInsightsCareerTotals
): PersonContributionTotalSummaryView | null {
  if (!hasContributionTotals(totals.source)) {
    return null;
  }

  return {
    key,
    label,
    amountLabel: formatCurrency(totals.total_individual_contribution_amount),
    itemizedAmountLabel: formatCurrency(totals.itemized_individual_contribution_amount),
    unitemizedAmountLabel: formatCurrency(totals.unitemized_individual_contribution_amount),
    transactionCountLabel: formatCountLabel(totals.itemized_transaction_count, "transaction"),
    caveatMessage: resolveTotalsCaveat(totals.source)
  };
}

function getLatestCycleTotal(
  cycleTotals: ContributionInsightsCycleTotal[]
): ContributionInsightsCycleTotal | null {
  return cycleTotals.reduce<ContributionInsightsCycleTotal | null>(
    (latest, current) => (latest === null || current.cycle > latest.cycle ? current : latest),
    null
  );
}

/**
 */
function buildTotalSummaryViews(
  insights: PersonContributionInsights
): PersonContributionTotalSummaryView[] {
  const latestCycle = getLatestCycleTotal(insights.cycle_totals);
  const views: PersonContributionTotalSummaryView[] = [];

  if (latestCycle !== null) {
    const cycleView = buildTotalSummaryView("cycle", `${latestCycle.cycle} cycle`, latestCycle);
    if (cycleView !== null) {
      views.push(cycleView);
    }
  }

  const careerView = buildTotalSummaryView(
    "career",
    buildRecentHistoryTotalLabel(insights.metadata.cycles_included),
    insights.career_totals
  );
  if (careerView !== null) {
    views.push(careerView);
  }

  return views;
}

function buildRecentHistoryTotalLabel(cyclesIncluded: number[]): string {
  if (cyclesIncluded.length === 0) {
    return "Recent history total";
  }

  const sortedCycles = [...cyclesIncluded].sort((left, right) => left - right);
  return `Recent history total (${sortedCycles[0]}-${sortedCycles[sortedCycles.length - 1]})`;
}

function formatOptionalCurrency(value: SerializedMoney | null | undefined): string {
  return value === null || value === undefined ? "Not available" : formatCurrency(value);
}

function formatMoneyTotal(amount: number): SerializedMoney {
  return amount.toFixed(2);
}

function sumMoney(summaries: CandidateFundraisingSummary[], field: PersonMoneyField): SerializedMoney {
  return formatMoneyTotal(
    summaries.reduce((total, summary) => total + parseMoney(summary[field]), 0)
  );
}

/**
 */
function sumOptionalMoney(
  summaries: CandidateFundraisingSummary[],
  field: "cash_on_hand" | "debts_owed_by_committee"
): SerializedMoney | null {
  const values: SerializedMoney[] = [];

  for (const summary of summaries) {
    const value = summary[field];
    if (value === null || value === undefined) {
      return null;
    }
    values.push(value);
  }

  return formatMoneyTotal(values.reduce((total, value) => total + parseMoney(value), 0));
}

function sumCount(summaries: CandidateFundraisingSummary[], field: PersonMoneyCountField): number {
  return summaries.reduce((total, summary) => total + Number(summary[field] ?? 0), 0);
}

function buildAggregateSummarySource(
  summaries: CandidateFundraisingSummary[]
): PersonMoneySummarySource {
  const uniqueSources = new Set(summaries.map((summary) => summary.summary_source));
  return uniqueSources.size === 1 ? summaries[0].summary_source : "mixed";
}

/**
 */
function buildAggregateReceiptSourceComposition(
  summaries: CandidateFundraisingSummary[]
): ReceiptSourceComponent[] {
  const totalsByLabel = new Map<string, ReceiptSourceComponent>();

  for (const summary of summaries) {
    for (const component of summary.receipt_source_composition) {
      const current = totalsByLabel.get(component.label);
      totalsByLabel.set(component.label, {
        label: component.label,
        total_amount: formatMoneyTotal(
          parseMoney(current?.total_amount ?? "0.00") + parseMoney(component.total_amount)
        ),
        source:
          current?.source === "none" || component.source === "none"
            ? "none"
            : "fec_committee_summary"
      });
    }
  }

  return [...totalsByLabel.values()];
}

function buildAggregateReceiptSourceCaveats(summaries: CandidateFundraisingSummary[]): string[] {
  return [...new Set(summaries.flatMap((summary) => summary.receipt_source_caveats))];
}

function getEarliestCoverageStart(summaries: CandidateFundraisingSummary[]): string {
  return summaries.reduce(
    (earliest, summary) =>
      summary.coverage_start_date < earliest ? summary.coverage_start_date : earliest,
    summaries[0].coverage_start_date
  );
}

function getLatestCoverageEnd(summaries: CandidateFundraisingSummary[]): string {
  return summaries.reduce(
    (latest, summary) => (summary.coverage_end_date > latest ? summary.coverage_end_date : latest),
    summaries[0].coverage_end_date
  );
}

function getSharedSelectedCycle(summaries: CandidateFundraisingSummary[]): number {
  const selectedCycle = summaries[0].selected_cycle;
  if (summaries.some((summary) => summary.selected_cycle !== selectedCycle)) {
    throw new Error("Person money at a glance summaries must share one selected cycle.");
  }

  return selectedCycle;
}

/**
 */
export function buildPersonMoneyAtGlanceSummary(
  summaries: CandidateFundraisingSummary[]
): PersonMoneyAtGlanceSummary {
  if (summaries.length === 0) {
    throw new Error("At least one candidate summary is required for person money at a glance.");
  }

  return {
    ...summaries[0],
    candidate_id: "person",
    candidate_name: "Person aggregate",
    selected_cycle: getSharedSelectedCycle(summaries),
    available_cycles: [...new Set(summaries.flatMap((summary) => summary.available_cycles))].sort(
      (left, right) => left - right
    ),
    coverage_start_date: getEarliestCoverageStart(summaries),
    coverage_end_date: getLatestCoverageEnd(summaries),
    total_raised: sumMoney(summaries, "total_raised"),
    total_spent: sumMoney(summaries, "total_spent"),
    net: sumMoney(summaries, "net"),
    transaction_count: sumCount(summaries, "transaction_count"),
    itemized_transaction_count: sumCount(summaries, "itemized_transaction_count"),
    cash_on_hand: sumOptionalMoney(summaries, "cash_on_hand"),
    debts_owed_by_committee: sumOptionalMoney(summaries, "debts_owed_by_committee"),
    summary_source: buildAggregateSummarySource(summaries),
    receipt_source_composition: buildAggregateReceiptSourceComposition(summaries),
    selected_cycle_coverage_complete: summaries.every(
      (summary) => summary.selected_cycle_coverage_complete
    ),
    can_render_share: summaries.every((summary) => summary.can_render_share),
    receipt_source_caveats: buildAggregateReceiptSourceCaveats(summaries),
    committees: summaries.flatMap((summary) => summary.committees)
  };
}

/**
 */
export function buildPersonMoneyAtGlancePresentation(
  summary: PersonMoneyAtGlanceSummary
): PersonMoneyAtGlancePresentation {
  return {
    heading: "Money at a glance",
    cycleLabel: `${summary.selected_cycle} cycle`,
    coverageLabel: formatCoverageLabel(summary.coverage_start_date, summary.coverage_end_date),
    sourceLabel: PERSON_SUMMARY_SOURCE_LABELS[summary.summary_source],
    cycleOptions: summary.available_cycles.map((cycle) => ({
      cycle,
      label: String(cycle),
      href: `?cycle=${cycle}`,
      selected: cycle === summary.selected_cycle
    })),
    metricRows: [
      { label: "Total receipts", value: formatCurrency(summary.total_raised) },
      { label: "Total disbursements", value: formatCurrency(summary.total_spent) },
      { label: "Cash on hand", value: formatOptionalCurrency(summary.cash_on_hand) },
      { label: "Debts owed by the committee", value: formatOptionalCurrency(summary.debts_owed_by_committee) }
    ],
    receiptComposition: buildPersonReceiptCompositionPresentation(summary)
  };
}

/**
 */
export function buildPersonContributionInsightsPresentation(
  insights: PersonContributionInsights,
  personTopDonors: RankedTransactionParty[] = [],
  personTopEmployers: PersonTopEmployerRow[] = []
): PersonContributionInsightsPresentation {
  const totalSummaryViews = buildTotalSummaryViews(insights);
  const hasDistrictGeography = insights.geography.by_district.length > 0;

  return {
    emptyMessage: resolveContributionInsightsEmptyMessage(insights),
    caveatMessages: resolveContributionInsightsCaveatMessages(insights),
    coverageLabel: formatCoverageLabel(
      insights.metadata.coverage_start_date,
      insights.metadata.coverage_end_date
    ),
    topDonors: buildRankedRowsWithBars(personTopDonors),
    topDonorsEmptyMessage:
      personTopDonors.length === 0 ? PERSON_TOP_DONORS_EMPTY_MESSAGE : null,
    topEmployers: buildTopEmployerRowsWithBars(personTopEmployers),
    topEmployersEmptyMessage:
      personTopEmployers.length === 0 ? PERSON_TOP_EMPLOYERS_EMPTY_MESSAGE : null,
    topEmployerDisclaimer: PERSON_TOP_EMPLOYER_DISCLAIMER,
    topEmployerMethodologyReference: PERSON_TOP_EMPLOYER_METHODOLOGY_REFERENCE,
    rankingLabels: {
      topDonors: "Top reported contributor names",
      topEmployers: "Top reported employer names"
    },
    totalSummaryViews,
    defaultTotalSummaryKey: totalSummaryViews[0]?.key ?? null,
    totalsEmptyMessage: totalSummaryViews.length === 0 ? PERSON_TOTALS_EMPTY_MESSAGE : null,
    smallDollarHeadline: formatSharePercent(insights.small_dollar_share.share),
    smallDollarSummary: buildSmallDollarSummary(insights),
    districtShareHeadline: formatDistrictShareHeadline(insights.geography.district_share.share),
    districtShareSummary: buildDistrictShareSummary(insights.geography.district_share),
    monthlyContributions: buildPersonMonthlyContributionsPresentation(insights),
    sizeBuckets: buildPersonSizeBucketPresentation(insights),
    geographyShare: buildPersonGeographySharePresentation(insights),
    unitemizedExclusionNote: DEFAULT_UNITEMIZED_EXCLUSION_NOTE,
    geographyNote: resolveContributionInsightsGeographyNote(insights, hasDistrictGeography)
  };
}

export function buildPersonLinkedCommitteeRows(
  summary: CandidateFundraisingSummary
): CandidateCommitteeBreakdownRow[] {
  return buildCandidateCommitteeBreakdown(summary);
}

export function buildPersonDonorVendorRows(
  transactions: CampaignFinanceTransactionResponse[]
): CommitteeTransactionRow[] {
  return buildCommitteeDeferredTransactionRows(transactions, {});
}

export function buildPersonLinkedCommitteeEmptyStateBanner(
  linkedCommitteeCount: number
): string | null {
  return buildLinkedCommitteeEmptyStateBanner(linkedCommitteeCount);
}

export function buildPersonDonorVendorEmptyStateBanner(
  donorVendorTransactionCount: number
): string | null {
  return buildDonorVendorEmptyStateBanner(donorVendorTransactionCount);
}

export function buildPersonOutsideSpendingSection(
  ieSummary: IndependentExpenditureSummary | null,
  ieTransactions: IndependentExpenditureResponse[]
): OutsideSpendingPresentation {
  return buildCandidateDeferredOutsideSpending(ieSummary, ieTransactions);
}
