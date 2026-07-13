/** View-model builders for civic detail pages and their record tables. */
import { formatCountLabel } from "$lib/count-label";
import { formatBoolean, formatDisplayValue } from "$lib/detail-format";
import type { ChartSeries } from "$lib/charts/types";
import {
  buildTrustSection,
  type TrustSectionViewModel
} from "$lib/detail-trust/presentation";
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import type {
  CandidateFundraisingSummary,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary
} from "$lib/campaign-finance-detail/contract";
import {
  buildCandidateDeferredCommitteeBreakdown,
  buildCandidateDeferredFundraisingSummary,
  buildCandidateDeferredKeyMetrics,
  buildCandidateDeferredOutsideSpending,
  type CandidateAggregateSummaryPresentation,
  type CandidateCommitteeBreakdownRow,
  type KeyMetric,
  type OutsideSpendingPresentation
} from "$lib/campaign-finance-detail/presentation";
import {
  OFFICE_LEVELS,
  buildCandidacyRoutePath,
  buildContestRoutePath,
  buildOfficeRoutePath,
  buildOfficeholdingRoutePath,
  type CandidacyDetailResponse,
  type CandidacySummary,
  type ContestDetailResponse,
  type OfficeDetailResponse,
  type OfficeIncompleteDataState,
  type OfficeholderSummary,
  type OfficeholdingDetailResponse
} from "$lib/civic-detail/contract";

export type CivicFactRow = {
  label: string;
  value: string;
};

export type CivicFullSectionKey = "summary" | "trust" | "metrics" | "records" | "caveats";
export type CivicCompactSectionKey = "summary" | "trust" | "metrics" | "caveats";

export type OfficeholderRow = {
  id: string;
  personName: string;
  holderStatus: string;
  personHref: string | null;
  officeholdingHref: string;
  linkAriaLabel: string;
};

export type OfficeCurrentHolderCard = {
  officeholdingId: string;
  personName: string;
  personHref: string | null;
  officeholdingHref: string;
  holderStatus: string;
  validFrom: string;
  validThrough: string;
  termEndEmphasis: string | null;
};

export type OfficeTimelineRow = {
  officeholdingId: string;
  personName: string;
  personHref: string | null;
  officeholdingHref: string;
  holderStatus: string;
  validFrom: string;
  validThrough: string;
  termEndEmphasis: string | null;
};

export type OfficeRecentContestRow = {
  contestId: string;
  contestName: string;
  contestHref: string;
  electionDate: string;
  electionType: string;
  filingDeadline: string;
  candidateCoverageNote: string | null;
};

export type ContestCandidacyRow = {
  id: string;
  personId: string;
  personName: string;
  personHref: string | null;
  candidacyHref: string;
  party: string;
  status: string;
  incumbentChallenge: string;
  isWinner: boolean;
  linkAriaLabel: string;
};

export type ContestCandidateFinanceSection = {
  personId: string;
  candidateHref: string | null;
  summary: CandidateFundraisingSummary | null;
  ieSummary: IndependentExpenditureSummary | null;
  ieTransactions: IndependentExpenditureResponse[];
};

export type ContestCandidateFinanceByPersonId = Record<string, ContestCandidateFinanceSection>;

export type ContestCandidateFinanceRow = {
  personId: string;
  personName: string;
  personHref: string | null;
  candidateHref: string | null;
  fundraisingSummary: CandidateAggregateSummaryPresentation | null;
  keyMetrics: KeyMetric[];
  committeeBreakdown: CandidateCommitteeBreakdownRow[];
  outsideSpending: OutsideSpendingPresentation;
  financeChartSeries: ChartSeries[];
  outsideSpendingChartSeries: ChartSeries[];
};

/**
 */
export type OfficeDetailPresentation = {
  title: string;
  sectionOrder: CivicFullSectionKey[];
  factRows: CivicFactRow[];
  keyMetricRows: CivicFactRow[];
  officeholderRows: OfficeholderRow[];
  currentHolderCard: OfficeCurrentHolderCard | null;
  currentHolderEmptyMessage: string | null;
  timelineRows: OfficeTimelineRow[];
  recentContestRows: OfficeRecentContestRow[];
  selectedElectoralDivisionId: string | null;
  trustSection: TrustSectionViewModel;
  officeholderEmptyMessage: string | null;
  timelineEmptyMessage: string | null;
  recentContestEmptyMessage: string | null;
  incompleteDataWarning: string | null;
};

/**
 */
export type ContestDetailPresentation = {
  title: string;
  sectionOrder: CivicFullSectionKey[];
  factRows: CivicFactRow[];
  keyMetricRows: CivicFactRow[];
  officeHref: string;
  selectedElectoralDivisionId: string | null;
  resultWinnerPersonName: string | null;
  resultWinnerPersonHref: string | null;
  resultWinnerCandidacyHref: string | null;
  resultEmptyMessage: string | null;
  candidacyRows: ContestCandidacyRow[];
  financeRows: ContestCandidateFinanceRow[];
  financeEmptyMessage: string | null;
  trustSection: TrustSectionViewModel;
  candidacyEmptyMessage: string | null;
  candidateListWarning: string | null;
};

export type CandidacyDetailPresentation = {
  title: string;
  sectionOrder: CivicCompactSectionKey[];
  factRows: CivicFactRow[];
  keyMetricRows: CivicFactRow[];
  personHref: string | null;
  contestHref: string;
  trustSection: TrustSectionViewModel;
  statusEmptyMessage: string | null;
};

export type OfficeholdingDetailPresentation = {
  title: string;
  sectionOrder: CivicCompactSectionKey[];
  factRows: CivicFactRow[];
  keyMetricRows: CivicFactRow[];
  personHref: string | null;
  officeHref: string;
  trustSection: TrustSectionViewModel;
  validPeriodEmptyMessage: string | null;
};

export type DetailRouteMetadata = {
  title: string;
  description: string;
};

const INCOMPLETE_DATA_WARNING_BY_STATE: Record<OfficeIncompleteDataState, string> = {
  no_officeholder: "Current officeholder data is incomplete for this office.",
  no_active_contest: "Active contest data is incomplete for this office."
};
const OFFICE_LEVEL_LABEL_BY_LEVEL: Readonly<Record<(typeof OFFICE_LEVELS)[number], string>> = {
  federal: "Federal",
  state: "State",
  county: "County",
  municipal: "Municipal",
  judicial: "Judicial",
  school_board: "School board",
  special_district: "Special district"
};

const CIVIC_FULL_SECTION_ORDER: CivicFullSectionKey[] = [
  "summary",
  "trust",
  "metrics",
  "records",
  "caveats"
];

const CIVIC_COMPACT_SECTION_ORDER: CivicCompactSectionKey[] = [
  "summary",
  "trust",
  "metrics",
  "caveats"
];

const OFFICEHOLDER_EMPTY_MESSAGE =
  "No current officeholders are linked yet. Check back after the next records refresh.";
const OFFICE_TIMELINE_EMPTY_MESSAGE =
  "No officeholding history is linked yet. Check back after the next records refresh.";
const OFFICE_RECENT_CONTEST_EMPTY_MESSAGE =
  "No recent contests are linked yet. Check back after the next records refresh.";
const CONTEST_CANDIDACY_EMPTY_MESSAGE =
  "No candidacies are linked yet. Check back after the next records refresh.";
const CONTEST_CANDIDATE_LIST_WARNING = "Candidate list coverage is incomplete for this contest.";
const CONTEST_RESULT_EMPTY_MESSAGE = "Results are not yet available for this contest.";
const CONTEST_FINANCE_EMPTY_MESSAGE =
  "Candidate finance and outside-spending data are not linked for this contest yet.";
const CANDIDACY_STATUS_EMPTY_MESSAGE = "Status is not available for this candidacy yet.";
const OFFICEHOLDING_PERIOD_EMPTY_MESSAGE =
  "No valid-period bounds are available for this officeholding.";
const OFFICE_CURRENT_HOLDER_EMPTY_MESSAGE =
  "No active officeholder is linked yet. Check back after the next records refresh.";

function formatDateValue(value: string | null): string {
  if (!value) {
    return "—";
  }

  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    return value.slice(0, 10);
  }

  return value;
}

function countOccurrences(values: string[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const v of values) {
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  return counts;
}

function parseSerializedMoney(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function parseDateSortValue(value: string | null): number {
  if (!value) {
    return Number.NEGATIVE_INFINITY;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

/**
 */
function assignUniqueAriaLabels(
  prefix: string,
  rows: { personName: string; disambiguator: string }[]
): string[] {
  const nameCounts = countOccurrences(rows.map((r) => r.personName));
  const nameOnly = rows.map((r) => `${prefix} ${r.personName}`);
  const withDisambiguator = rows.map(
    (r) => `${prefix} ${r.personName}, ${r.disambiguator}`
  );
  const disambiguatorCounts = countOccurrences(withDisambiguator);

  const disambiguatorSeen = new Map<string, number>();
  return rows.map((r, i) => {
    if ((nameCounts.get(r.personName) ?? 0) <= 1) {
      return nameOnly[i];
    }
    const withMeta = withDisambiguator[i];
    if ((disambiguatorCounts.get(withMeta) ?? 0) <= 1) {
      return withMeta;
    }
    const seen = (disambiguatorSeen.get(withMeta) ?? 0) + 1;
    disambiguatorSeen.set(withMeta, seen);
    return `${withMeta} (#${seen})`;
  });
}

/**
 */
function buildOfficeholderRows(officeholders: OfficeholderSummary[]): OfficeholderRow[] {
  const baseRows = officeholders.map((officeholder) => ({
    id: officeholder.officeholding_id,
    personName: officeholder.person_name,
    holderStatus: officeholder.holder_status,
    personHref: buildEntityRouteHref("person", officeholder.person_id),
    officeholdingHref: buildOfficeholdingRoutePath(officeholder.officeholding_id)
  }));

  const labels = assignUniqueAriaLabels(
    "View officeholding detail for",
    baseRows.map((r) => ({ personName: r.personName, disambiguator: r.holderStatus }))
  );

  return baseRows.map((row, i) => ({ ...row, linkAriaLabel: labels[i] }));
}

function buildIncompleteDataWarning(incompleteStates: OfficeIncompleteDataState[]): string | null {
  if (incompleteStates.length === 0) {
    return null;
  }

  return incompleteStates
    .map((state) => INCOMPLETE_DATA_WARNING_BY_STATE[state])
    .join(" ");
}

/**
 */
function formatOfficeLevel(officeLevel: string): string {
  const mappedLabel = OFFICE_LEVEL_LABEL_BY_LEVEL[officeLevel as (typeof OFFICE_LEVELS)[number]];
  if (mappedLabel) {
    return mappedLabel;
  }

  return officeLevel
    .split("_")
    .map((segment) => {
      if (segment.length === 0) {
        return segment;
      }

      return `${segment[0].toUpperCase()}${segment.slice(1)}`;
    })
    .join(" ");
}

function buildOfficeFactRows(detail: OfficeDetailResponse): CivicFactRow[] {
  return [
    { label: "Name", value: detail.name },
    { label: "Title", value: formatDisplayValue(detail.title) },
    { label: "Office level", value: formatOfficeLevel(detail.office_level) },
    { label: "State", value: formatDisplayValue(detail.state) },
    { label: "Elected", value: formatBoolean(detail.is_elected) },
    { label: "Number of seats", value: formatDisplayValue(detail.number_of_seats) }
  ];
}

function buildOfficeKeyMetricRows(officeholderRows: OfficeholderRow[]): CivicFactRow[] {
  return [{ label: "Current officeholders", value: String(officeholderRows.length) }];
}

type OfficeCurrentHolderCardLike = {
  officeholding_id: string;
  person_id: string;
  person_name: string;
  holder_status: string;
  valid_period_lower?: string | null;
  valid_period_upper?: string | null;
};

function isOfficeCurrentHolderCardValue(value: unknown): value is OfficeCurrentHolderCardLike {
  if (value === null || value === undefined || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.officeholding_id === "string" &&
    typeof candidate.person_id === "string" &&
    typeof candidate.person_name === "string" &&
    typeof candidate.holder_status === "string"
  );
}

/**
 */
function buildOfficeCurrentHolderCard(detail: OfficeDetailResponse): OfficeCurrentHolderCard | null {
  const holder = detail.current_holder_card;
  if (!isOfficeCurrentHolderCardValue(holder)) {
    const fallbackOfficeholders = Array.isArray(detail.current_officeholders)
      ? detail.current_officeholders
      : [];
    if (fallbackOfficeholders.length !== 1) {
      return null;
    }
    const fallbackHolder = fallbackOfficeholders[0];
    return {
      officeholdingId: fallbackHolder.officeholding_id,
      personName: fallbackHolder.person_name,
      personHref: buildEntityRouteHref("person", fallbackHolder.person_id),
      officeholdingHref: buildOfficeholdingRoutePath(fallbackHolder.officeholding_id),
      holderStatus: fallbackHolder.holder_status,
      validFrom: formatDateValue(null),
      validThrough: formatDateValue(null),
      termEndEmphasis: null
    };
  }

  return {
    officeholdingId: holder.officeholding_id,
    personName: holder.person_name,
    personHref: buildEntityRouteHref("person", holder.person_id),
    officeholdingHref: buildOfficeholdingRoutePath(holder.officeholding_id),
    holderStatus: holder.holder_status,
    validFrom: formatDateValue(holder.valid_period_lower),
    validThrough: formatDateValue(holder.valid_period_upper),
    termEndEmphasis: null
  };
}

/**
 */
function buildOfficeCurrentHolderEmptyMessage(
  detail: OfficeDetailResponse,
  officeholderRows: OfficeholderRow[],
  currentHolderCard: OfficeCurrentHolderCard | null
): string | null {
  if (currentHolderCard !== null) {
    return null;
  }
  if (detail.current_holder_card === undefined) {
    return OFFICE_CURRENT_HOLDER_EMPTY_MESSAGE;
  }
  if (
    detail.current_holder_card !== null &&
    !isOfficeCurrentHolderCardValue(detail.current_holder_card)
  ) {
    return OFFICE_CURRENT_HOLDER_EMPTY_MESSAGE;
  }
  if (officeholderRows.length > 0) {
    return null;
  }
  return OFFICE_CURRENT_HOLDER_EMPTY_MESSAGE;
}

/**
 */
function buildOfficeTimelineRows(detail: OfficeDetailResponse): OfficeTimelineRow[] {
  // Some smoke fixtures can lag the backend contract during staged rollout.
  // Keep the renderer resilient by treating missing timeline payloads as empty.
  const rows = Array.isArray(detail.officeholding_timeline)
    ? [...detail.officeholding_timeline]
    : [];
  rows.sort((a, b) => {
    if (a.is_active !== b.is_active) {
      return a.is_active ? -1 : 1;
    }
    const lowerDiff = parseDateSortValue(b.valid_period_lower) - parseDateSortValue(a.valid_period_lower);
    if (lowerDiff !== 0) {
      return lowerDiff;
    }
    const upperDiff = parseDateSortValue(b.valid_period_upper) - parseDateSortValue(a.valid_period_upper);
    if (upperDiff !== 0) {
      return upperDiff;
    }
    return a.person_name.localeCompare(b.person_name);
  });

  return rows.map((timelineRow) => {
    // Defer to backend-owned ended state so the presenter does not invent a
    // second active-period rule (status proxy or wall-clock parsing).
    const hasTermEnded = timelineRow.term_ended && timelineRow.valid_period_upper !== null;

    return {
      officeholdingId: timelineRow.officeholding_id,
      personName: timelineRow.person_name,
      personHref: buildEntityRouteHref("person", timelineRow.person_id),
      officeholdingHref: buildOfficeholdingRoutePath(timelineRow.officeholding_id),
      holderStatus: timelineRow.holder_status,
      validFrom: formatDateValue(timelineRow.valid_period_lower),
      validThrough: formatDateValue(timelineRow.valid_period_upper),
      termEndEmphasis: hasTermEnded
        ? `Term ended ${formatDateValue(timelineRow.valid_period_upper)}`
        : null
    };
  });
}

/**
 */
function buildOfficeRecentContestRows(detail: OfficeDetailResponse): OfficeRecentContestRow[] {
  const rows = Array.isArray(detail.recent_contests) ? [...detail.recent_contests] : [];
  rows.sort((a, b) => {
    const electionDiff = parseDateSortValue(b.election_date) - parseDateSortValue(a.election_date);
    if (electionDiff !== 0) {
      return electionDiff;
    }
    return a.contest_name.localeCompare(b.contest_name);
  });

  return rows.map((contest) => ({
    contestId: contest.contest_id,
    contestName: contest.contest_name,
    contestHref: buildContestRoutePath(contest.contest_id),
    electionDate: formatDateValue(contest.election_date),
    electionType: contest.election_type,
    filingDeadline: formatDateValue(contest.filing_deadline),
    candidateCoverageNote: contest.candidate_list_incomplete
      ? "Candidate list coverage is incomplete for this contest."
      : null
  }));
}

/**
 */
function buildContestCandidacyRows(
  candidacies: CandidacySummary[],
  winnerCandidacyId: string | null | undefined
): ContestCandidacyRow[] {
  const baseRows = candidacies.map((candidacy) => ({
    id: candidacy.candidacy_id,
    personId: candidacy.person_id,
    personName: candidacy.person_name,
    personHref: buildEntityRouteHref("person", candidacy.person_id),
    candidacyHref: buildCandidacyRoutePath(candidacy.candidacy_id),
    party: formatDisplayValue(candidacy.party),
    status: formatDisplayValue(candidacy.status),
    incumbentChallenge: formatDisplayValue(candidacy.incumbent_challenge),
    isWinner: candidacy.candidacy_id === winnerCandidacyId
  }));

  const labels = assignUniqueAriaLabels(
    "View candidacy detail for",
    candidacies.map((c) => ({
      personName: c.person_name,
      disambiguator: c.party ?? "no party"
    }))
  );

  return baseRows.map((row, i) => ({
    ...row,
    linkAriaLabel:
      row.isWinner && !labels[i].includes(", winner") ? `${labels[i]}, winner` : labels[i]
  }));
}

function buildContestFactRows(detail: ContestDetailResponse): CivicFactRow[] {
  return [
    { label: "Name", value: detail.name },
    { label: "Election date", value: formatDateValue(detail.election_date) },
    { label: "Election type", value: detail.election_type },
    { label: "Filing deadline", value: formatDateValue(detail.filing_deadline) },
    { label: "Partisan", value: formatBoolean(detail.is_partisan) },
    { label: "Number of seats", value: formatDisplayValue(detail.number_of_seats) }
  ];
}

function buildContestKeyMetricRows(candidacyRows: ContestCandidacyRow[]): CivicFactRow[] {
  return [{ label: "Candidacies", value: String(candidacyRows.length) }];
}

/**
 */
function buildContestFinanceChartSeries(
  candidateName: string,
  summary: CandidateFundraisingSummary
): ChartSeries[] {
  return [
    {
      id: "candidate-finance",
      label: `${candidateName} fundraising`,
      points: [
        { x: "Raised", y: parseSerializedMoney(summary.total_raised) },
        { x: "Spent", y: parseSerializedMoney(summary.total_spent) },
        { x: "Net", y: parseSerializedMoney(summary.net) }
      ]
    }
  ];
}

/**
 */
function buildContestOutsideSpendingChartSeries(
  candidateName: string,
  ieSummary: IndependentExpenditureSummary | null
): ChartSeries[] {
  if (ieSummary === null) {
    return [];
  }

  return [
    {
      id: "outside-spending",
      label: `${candidateName} outside spending`,
      points: [
        { x: "Support", y: parseSerializedMoney(ieSummary.support_total) },
        { x: "Oppose", y: parseSerializedMoney(ieSummary.oppose_total) }
      ]
    }
  ];
}

/**
 */
function buildContestCandidateFinanceRows(
  candidacyRows: ContestCandidacyRow[],
  candidateFinanceByPersonId: ContestCandidateFinanceByPersonId
): ContestCandidateFinanceRow[] {
  const rows: ContestCandidateFinanceRow[] = [];

  for (const candidacyRow of candidacyRows) {
    const financeSection = candidateFinanceByPersonId[candidacyRow.personId];
    if (!financeSection) {
      continue;
    }

    const fundraisingSummary =
      financeSection.summary === null
        ? null
        : buildCandidateDeferredFundraisingSummary(financeSection.summary);
    rows.push({
      personId: candidacyRow.personId,
      personName: candidacyRow.personName,
      personHref: candidacyRow.personHref,
      candidateHref: financeSection.candidateHref,
      fundraisingSummary,
      keyMetrics:
        financeSection.summary === null ? [] : buildCandidateDeferredKeyMetrics(financeSection.summary),
      committeeBreakdown:
        financeSection.summary === null
          ? []
          : buildCandidateDeferredCommitteeBreakdown(financeSection.summary),
      outsideSpending: buildCandidateDeferredOutsideSpending(
        financeSection.ieSummary,
        financeSection.ieTransactions
      ),
      financeChartSeries:
        financeSection.summary === null
          ? []
          : buildContestFinanceChartSeries(candidacyRow.personName, financeSection.summary),
      outsideSpendingChartSeries: buildContestOutsideSpendingChartSeries(
        candidacyRow.personName,
        financeSection.ieSummary
      )
    });
  }

  return rows;
}

function buildCandidacyFactRows(detail: CandidacyDetailResponse): CivicFactRow[] {
  return [
    { label: "Person", value: detail.person_name },
    { label: "Party", value: formatDisplayValue(detail.party) },
    { label: "Filing date", value: formatDateValue(detail.filing_date) },
    { label: "Status", value: formatDisplayValue(detail.status) },
    { label: "Incumbent/challenger", value: formatDisplayValue(detail.incumbent_challenge) },
    { label: "Candidate number", value: formatDisplayValue(detail.candidate_number) }
  ];
}

function buildCandidacyKeyMetricRows(detail: CandidacyDetailResponse): CivicFactRow[] {
  return [{ label: "Has filing date", value: detail.filing_date ? "Yes" : "No" }];
}

function buildOfficeholdingFactRows(detail: OfficeholdingDetailResponse): CivicFactRow[] {
  return [
    { label: "Person", value: detail.person_name },
    { label: "Holder status", value: detail.holder_status },
    { label: "Valid from", value: formatDateValue(detail.valid_period_lower) },
    { label: "Valid through", value: formatDateValue(detail.valid_period_upper) },
    { label: "Date precision", value: detail.date_precision }
  ];
}

function buildOfficeholdingKeyMetricRows(detail: OfficeholdingDetailResponse): CivicFactRow[] {
  const isActive =
    detail.holder_status !== "former" &&
    detail.valid_period_lower !== null &&
    detail.valid_period_upper === null;
  return [{ label: "Active officeholding", value: isActive ? "Yes" : "No" }];
}

export function buildOfficeDetailMetadata(
  officeName: string,
  officeholderCount: number
): DetailRouteMetadata {
  const officeholderCountLabel = formatCountLabel(officeholderCount, "current officeholder");

  return {
    title: `${officeName} | Office | Civibus`,
    description: `Office profile with ${officeholderCountLabel}.`
  };
}

export function buildOfficeDetailMetadataFromDetail(detail: OfficeDetailResponse): DetailRouteMetadata {
  return buildOfficeDetailMetadata(detail.name, detail.current_officeholders.length);
}

export function buildContestDetailMetadata(
  contestName: string,
  candidacyCount: number
): DetailRouteMetadata {
  const candidacyCountLabel = formatCountLabel(candidacyCount, "candidacy");

  return {
    title: `${contestName} | Contest | Civibus`,
    description: `Contest profile with ${candidacyCountLabel}.`
  };
}

export function buildContestDetailMetadataFromDetail(detail: ContestDetailResponse): DetailRouteMetadata {
  return buildContestDetailMetadata(detail.name, detail.candidacies.length);
}

export function buildCandidacyDetailMetadata(personName: string): DetailRouteMetadata {
  return {
    title: `${personName} | Candidacy | Civibus`,
    description: `Candidacy profile for ${personName}.`
  };
}

export function buildCandidacyDetailMetadataFromDetail(detail: CandidacyDetailResponse): DetailRouteMetadata {
  return buildCandidacyDetailMetadata(detail.person_name);
}

export function buildOfficeholdingDetailMetadata(personName: string): DetailRouteMetadata {
  return {
    title: `${personName} | Officeholding | Civibus`,
    description: `Officeholding profile for ${personName}.`
  };
}

export function buildOfficeholdingDetailMetadataFromDetail(
  detail: OfficeholdingDetailResponse
): DetailRouteMetadata {
  return buildOfficeholdingDetailMetadata(detail.person_name);
}

/**
 */
export function buildOfficeDetailPresentation(detail: OfficeDetailResponse): OfficeDetailPresentation {
  const officeholderRows = buildOfficeholderRows(detail.current_officeholders);
  const timelineRows = buildOfficeTimelineRows(detail);
  const recentContestRows = buildOfficeRecentContestRows(detail);
  const currentHolderCard = buildOfficeCurrentHolderCard(detail);

  return {
    title: detail.name,
    sectionOrder: CIVIC_FULL_SECTION_ORDER,
    factRows: buildOfficeFactRows(detail),
    keyMetricRows: buildOfficeKeyMetricRows(officeholderRows),
    officeholderRows,
    currentHolderCard,
    currentHolderEmptyMessage: buildOfficeCurrentHolderEmptyMessage(
      detail,
      officeholderRows,
      currentHolderCard
    ),
    timelineRows,
    recentContestRows,
    selectedElectoralDivisionId: detail.selected_electoral_division_id,
    trustSection: buildTrustSection(detail.sources),
    officeholderEmptyMessage: officeholderRows.length === 0 ? OFFICEHOLDER_EMPTY_MESSAGE : null,
    timelineEmptyMessage: timelineRows.length === 0 ? OFFICE_TIMELINE_EMPTY_MESSAGE : null,
    recentContestEmptyMessage:
      recentContestRows.length === 0 ? OFFICE_RECENT_CONTEST_EMPTY_MESSAGE : null,
    incompleteDataWarning: buildIncompleteDataWarning(detail.incomplete_data_states)
  };
}

type BuildContestDetailPresentationOptions = {
  candidateFinanceByPersonId?: ContestCandidateFinanceByPersonId;
};

/**
 */
export function buildContestDetailPresentation(
  detail: ContestDetailResponse,
  options?: BuildContestDetailPresentationOptions
): ContestDetailPresentation {
  const candidacyRows = buildContestCandidacyRows(detail.candidacies, detail.result_winner_candidacy_id);
  const candidateFinanceByPersonId = options?.candidateFinanceByPersonId ?? {};
  const financeRows = buildContestCandidateFinanceRows(candidacyRows, candidateFinanceByPersonId);

  const matchedWinnerRow =
    detail.result_winner_candidacy_id === undefined || detail.result_winner_candidacy_id === null
      ? null
      : candidacyRows.find((row) => row.id === detail.result_winner_candidacy_id) ?? null;
  const resultWinnerPersonName =
    detail.result_winner_person_name ?? matchedWinnerRow?.personName ?? null;
  const resultWinnerPersonHref =
    detail.result_winner_person_id === undefined || detail.result_winner_person_id === null
      ? matchedWinnerRow?.personHref ?? null
      : buildEntityRouteHref("person", detail.result_winner_person_id);
  const resultWinnerCandidacyHref = matchedWinnerRow?.candidacyHref ?? null;

  return {
    title: detail.name,
    sectionOrder: CIVIC_FULL_SECTION_ORDER,
    factRows: buildContestFactRows(detail),
    keyMetricRows: buildContestKeyMetricRows(candidacyRows),
    officeHref: buildOfficeRoutePath(detail.office_id),
    selectedElectoralDivisionId: detail.electoral_division_id,
    resultWinnerPersonName,
    resultWinnerPersonHref,
    resultWinnerCandidacyHref,
    resultEmptyMessage: resultWinnerPersonName === null ? CONTEST_RESULT_EMPTY_MESSAGE : null,
    candidacyRows,
    financeRows,
    financeEmptyMessage: financeRows.length === 0 ? CONTEST_FINANCE_EMPTY_MESSAGE : null,
    trustSection: buildTrustSection(detail.sources),
    candidacyEmptyMessage: candidacyRows.length === 0 ? CONTEST_CANDIDACY_EMPTY_MESSAGE : null,
    candidateListWarning: detail.candidate_list_incomplete ? CONTEST_CANDIDATE_LIST_WARNING : null
  };
}

export function buildCandidacyDetailPresentation(detail: CandidacyDetailResponse): CandidacyDetailPresentation {
  return {
    title: `${detail.person_name} candidacy`,
    sectionOrder: CIVIC_COMPACT_SECTION_ORDER,
    factRows: buildCandidacyFactRows(detail),
    keyMetricRows: buildCandidacyKeyMetricRows(detail),
    personHref: buildEntityRouteHref("person", detail.person_id),
    contestHref: buildContestRoutePath(detail.contest_id),
    trustSection: buildTrustSection(detail.sources),
    statusEmptyMessage: detail.status ? null : CANDIDACY_STATUS_EMPTY_MESSAGE
  };
}

/** Assembles the officeholding detail presentation model from the API payload. */
export function buildOfficeholdingDetailPresentation(
  detail: OfficeholdingDetailResponse
): OfficeholdingDetailPresentation {
  return {
    title: `${detail.person_name} officeholding`,
    sectionOrder: CIVIC_COMPACT_SECTION_ORDER,
    factRows: buildOfficeholdingFactRows(detail),
    keyMetricRows: buildOfficeholdingKeyMetricRows(detail),
    personHref: buildEntityRouteHref("person", detail.person_id),
    officeHref: buildOfficeRoutePath(detail.office_id),
    trustSection: buildTrustSection(detail.sources),
    validPeriodEmptyMessage:
      detail.valid_period_lower === null && detail.valid_period_upper === null
        ? OFFICEHOLDING_PERIOD_EMPTY_MESSAGE
        : null
  };
}
