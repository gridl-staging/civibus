/** Presentation builders for public person and organization detail pages. */
import {
  buildCandidateDeferredFundraisingSummary,
  buildCandidateDeferredOutsideSpending,
  buildCandidateCommitteeBreakdown,
  buildCommitteeDeferredTransactionRows,
  buildRankedPartyRows,
  formatCurrency,
  type CandidateAggregateSummaryPresentation,
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
  SerializedMoney
} from "$lib/campaign-finance-detail/contract";
import type { ChartSeries } from "$lib/charts/types";
import { formatDisplayValue } from "$lib/detail-format";
import { formatCountLabel } from "$lib/count-label";
import {
  buildDonorVendorEmptyStateBanner,
  buildLinkedCommitteeEmptyStateBanner,
  buildTrustSection,
  type TrustSectionViewModel
} from "$lib/detail-trust/presentation";
import type {
  EntityDetailResponse,
  OrgDetailResponse,
  PersonDetailResponse,
  Stage4EntityType
} from "$lib/entity-detail/contract";

export type DetailFactRow = {
  label: string;
  value: string;
};

export type EntityDetailSectionKey =
  | "summary"
  | "trust"
  | "metrics"
  | "records"
  | "person-campaign-finance";

export type DetailRouteMetadata = {
  title: string;
  description: string;
};

export type EntityDetailMetadataInput = {
  entityType: Stage4EntityType;
  canonicalName: string;
  identifierCount: number;
};

export type EntityDetailMetadataFromDetailInput = {
  entityType: Stage4EntityType;
  detail: EntityDetailResponse;
};

export type EntityDetailShellInput = {
  entityType: Stage4EntityType;
  detail: EntityDetailResponse;
};

export type EntityDetailShellPresentation = {
  entityType: Stage4EntityType;
  canonicalName: string;
  sectionOrder: EntityDetailSectionKey[];
  coreFactRows: DetailFactRow[];
  keyMetricRows: DetailFactRow[];
  identifierRows: DetailFactRow[];
  trustSection: TrustSectionViewModel;
  identifierEmptyMessage: string | null;
};

export type EntityDetailPresentation = EntityDetailShellPresentation;

/**
 */
export type PersonContributionInsightsPresentation = {
  emptyMessage: string | null;
  caveatMessages: string[];
  coverageLabel: string;
  topDonors: RankedPartyRow[];
  topDonorsEmptyMessage: string | null;
  topEmployers: RankedPartyRow[];
  topEmployersEmptyMessage: string | null;
  topEmployerDisclaimer: string;
  topEmployerMethodologyReference: string;
  totalSummaryViews: PersonContributionTotalSummaryView[];
  defaultTotalSummaryKey: PersonContributionTotalSummaryKey | null;
  totalsEmptyMessage: string | null;
  smallDollarHeadline: string;
  smallDollarSummary: string;
  districtShareHeadline: string;
  districtShareSummary: string;
  monthlyTotalsSeries: ChartSeries[];
  itemizedCountSeries: ChartSeries[];
  dollarsBySizeSeries: ChartSeries[];
  stateGeographySeries: ChartSeries[];
  districtGeographySeries: ChartSeries[];
  preferredGeographySeries: ChartSeries[];
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

const ENTITY_TYPE_LABELS: Record<Stage4EntityType, string> = {
  person: "Person",
  org: "Organization"
};

const IDENTIFIER_EMPTY_MESSAGE =
  "No identifiers are available yet. Check related records after the next refresh.";
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
    "Committee summary totals are unavailable, so summary-backed unitemized dollars are not included."
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

const PERSON_SECTION_ORDER: EntityDetailSectionKey[] = [
  "summary",
  "trust",
  "metrics",
  "records",
  "person-campaign-finance"
];
const ORG_SECTION_ORDER: EntityDetailSectionKey[] = ["summary", "trust", "metrics", "records"];

export function buildEntityDetailMetadata(input: EntityDetailMetadataInput): DetailRouteMetadata {
  const entityTypeLabel = ENTITY_TYPE_LABELS[input.entityType];

  return {
    title: `${input.canonicalName} | ${entityTypeLabel} | Civibus`,
    description: `${entityTypeLabel} profile with ${input.identifierCount} ${formatIdentifierLabel(input.identifierCount)} and source-linked records.`
  };
}

export function buildEntityDetailMetadataFromDetail(
  input: EntityDetailMetadataFromDetailInput
): DetailRouteMetadata {
  return buildEntityDetailMetadata({
    entityType: input.entityType,
    canonicalName: input.detail.canonical_name,
    identifierCount: Object.keys(input.detail.identifiers).length
  });
}

function formatIdentifierLabel(count: number): string {
  return count === 1 ? "identifier" : "identifiers";
}

function buildSharedFactRows(detail: EntityDetailResponse): DetailFactRow[] {
  return [{ label: "Canonical name", value: detail.canonical_name }];
}

/**
 */
export function buildCanonicalDetailFacts(
  entityType: Stage4EntityType,
  detail: EntityDetailResponse
): DetailFactRow[] {
  const sharedRows = buildSharedFactRows(detail);

  if (entityType === "person") {
    const personDetail = detail as PersonDetailResponse;

    return [
      ...sharedRows,
      { label: "First name", value: formatDisplayValue(personDetail.first_name) },
      { label: "Last name", value: formatDisplayValue(personDetail.last_name) },
      { label: "Occupation", value: formatDisplayValue(personDetail.occupation) },
      { label: "Education", value: formatDisplayValue(personDetail.education) },
      { label: "Year of birth", value: formatDisplayValue(personDetail.year_of_birth) }
    ];
  }

  const organizationDetail = detail as OrgDetailResponse;

  return [
    ...sharedRows,
    { label: "Organization type", value: formatDisplayValue(organizationDetail.org_type) },
    { label: "Registered state", value: formatDisplayValue(organizationDetail.registered_state) },
    { label: "Formation date", value: formatDisplayValue(organizationDetail.formation_date) }
  ];
}

export function buildIdentifierRows(identifiers: Record<string, string>): DetailFactRow[] {
  return Object.entries(identifiers)
    .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
    .map(([label, value]) => ({ label, value }));
}

export function buildIdentifierKeyMetrics(identifierRows: DetailFactRow[]): DetailFactRow[] {
  return [{ label: "Identifiers", value: String(identifierRows.length) }];
}

export function getIdentifierEmptyMessage(): string {
  return IDENTIFIER_EMPTY_MESSAGE;
}

function parseMoney(value: SerializedMoney): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
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

  // The backend share denominator excludes Unknown district; keep that rule explicit in copy.
  return `${baseSummary}; ${formatCurrency(
    districtShare.unknown_district_amount
  )} unknown district excluded from the share.`;
}

function buildTopEmployerRows(personTopEmployers: PersonTopEmployerRow[]): RankedPartyRow[] {
  // Employer rows are raw employer-name buckets, not industry or sector classifications.
  return buildRankedPartyRows(
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

  const careerView = buildTotalSummaryView("career", "Career", insights.career_totals);
  if (careerView !== null) {
    views.push(careerView);
  }

  return views;
}

/**
 */
export function buildPersonContributionInsightsPresentation(
  insights: PersonContributionInsights,
  personTopDonors: RankedTransactionParty[] = [],
  personTopEmployers: PersonTopEmployerRow[] = []
): PersonContributionInsightsPresentation {
  const totalSummaryViews = buildTotalSummaryViews(insights);
  const stateGeographySeries = buildSingleSeries(
    "state-geography",
    "State geography",
    insights.geography.by_state.map((row) => ({
      x: row.label,
      y: parseMoney(row.total_amount)
    }))
  );
  const districtGeographySeries = buildSingleSeries(
    "district-geography",
    "District geography",
    insights.geography.by_district.map((row) => ({
      x: row.label,
      y: parseMoney(row.total_amount)
    }))
  );
  const hasDistrictGeography = insights.geography.by_district.length > 0;

  return {
    emptyMessage: resolveContributionInsightsEmptyMessage(insights),
    caveatMessages: resolveContributionInsightsCaveatMessages(insights),
    coverageLabel: formatCoverageLabel(
      insights.metadata.coverage_start_date,
      insights.metadata.coverage_end_date
    ),
    topDonors: buildRankedPartyRows(personTopDonors),
    topDonorsEmptyMessage:
      personTopDonors.length === 0 ? PERSON_TOP_DONORS_EMPTY_MESSAGE : null,
    topEmployers: buildTopEmployerRows(personTopEmployers),
    topEmployersEmptyMessage:
      personTopEmployers.length === 0 ? PERSON_TOP_EMPLOYERS_EMPTY_MESSAGE : null,
    topEmployerDisclaimer: PERSON_TOP_EMPLOYER_DISCLAIMER,
    topEmployerMethodologyReference: PERSON_TOP_EMPLOYER_METHODOLOGY_REFERENCE,
    totalSummaryViews,
    defaultTotalSummaryKey: totalSummaryViews[0]?.key ?? null,
    totalsEmptyMessage: totalSummaryViews.length === 0 ? PERSON_TOTALS_EMPTY_MESSAGE : null,
    smallDollarHeadline: formatSharePercent(insights.small_dollar_share.share),
    smallDollarSummary: buildSmallDollarSummary(insights),
    districtShareHeadline: formatDistrictShareHeadline(insights.geography.district_share.share),
    districtShareSummary: buildDistrictShareSummary(insights.geography.district_share),
    monthlyTotalsSeries: buildSingleSeries(
      "monthly-totals",
      "Donations over time",
      insights.monthly_totals.map((row) => ({
        x: row.month,
        y: parseMoney(row.total_amount)
      }))
    ),
    itemizedCountSeries: buildSingleSeries(
      "itemized-counts",
      "Donation count by size bucket",
      insights.itemized_size_buckets.map((bucket) => ({
        x: bucket.label,
        y: bucket.transaction_count
      }))
    ),
    dollarsBySizeSeries: buildSingleSeries(
      "dollars-by-size",
      "Dollars by size bucket",
      insights.dollars_by_size.map((bucket) => ({
        x: bucket.label,
        y: parseMoney(bucket.total_amount)
      }))
    ),
    stateGeographySeries,
    districtGeographySeries,
    preferredGeographySeries: hasDistrictGeography ? districtGeographySeries : stateGeographySeries,
    unitemizedExclusionNote: DEFAULT_UNITEMIZED_EXCLUSION_NOTE,
    geographyNote: resolveContributionInsightsGeographyNote(insights, hasDistrictGeography)
  };
}

/**
 */
export function buildPersonSummaryChartSeries(summary: {
  total_raised: SerializedMoney;
  total_spent: SerializedMoney;
  net: SerializedMoney;
}): ChartSeries[] {
  return [
    {
      id: "finance",
      label: "Finance",
      points: [
        { x: "Raised", y: parseMoney(summary.total_raised) },
        { x: "Spent", y: parseMoney(summary.total_spent) },
        { x: "Net", y: parseMoney(summary.net) }
      ]
    }
  ];
}

/**
 */
export function buildPersonOutsideSpendingChartSeries(summary: {
  support_total: SerializedMoney;
  oppose_total: SerializedMoney;
} | null): ChartSeries[] {
  if (summary === null) {
    return [];
  }

  return [
    {
      id: "outside-spending",
      label: "Outside spending",
      points: [
        { x: "Support", y: parseMoney(summary.support_total) },
        { x: "Oppose", y: parseMoney(summary.oppose_total) }
      ]
    }
  ];
}

export function buildPersonFinanceSummaryPresentation(
  summary: CandidateFundraisingSummary
): CandidateAggregateSummaryPresentation {
  return buildCandidateDeferredFundraisingSummary(summary);
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

export function buildPersonLinkedCommitteeEmptyStateBanner(linkedCommitteeCount: number): string | null {
  return buildLinkedCommitteeEmptyStateBanner(linkedCommitteeCount);
}

export function buildPersonDonorVendorEmptyStateBanner(donorVendorTransactionCount: number): string | null {
  return buildDonorVendorEmptyStateBanner(donorVendorTransactionCount);
}

export function buildPersonOutsideSpendingSection(
  ieSummary: IndependentExpenditureSummary | null,
  ieTransactions: IndependentExpenditureResponse[]
): OutsideSpendingPresentation {
  return buildCandidateDeferredOutsideSpending(ieSummary, ieTransactions);
}

/**
 */
export function buildEntityDetailShellPresentation(
  input: EntityDetailShellInput
): EntityDetailShellPresentation {
  const identifierRows = buildIdentifierRows(input.detail.identifiers);

  return {
    entityType: input.entityType,
    canonicalName: input.detail.canonical_name,
    sectionOrder: input.entityType === "person" ? PERSON_SECTION_ORDER : ORG_SECTION_ORDER,
    coreFactRows: buildCanonicalDetailFacts(input.entityType, input.detail),
    keyMetricRows: buildIdentifierKeyMetrics(identifierRows),
    identifierRows,
    trustSection: buildTrustSection(input.detail.sources),
    identifierEmptyMessage: identifierRows.length === 0 ? getIdentifierEmptyMessage() : null
  };
}

export function buildEntityDetailPresentation(
  input: EntityDetailShellInput
): EntityDetailPresentation {
  return buildEntityDetailShellPresentation(input);
}
