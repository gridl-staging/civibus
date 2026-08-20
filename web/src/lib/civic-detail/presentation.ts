/** View-model builders for civic detail pages and their record tables. */
import { formatCountLabel } from "$lib/count-label";
import { formatBoolean, formatDisplayValue } from "$lib/detail-format";
import { buildTrustSection, type TrustSectionViewModel } from "$lib/detail-trust/presentation";
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import { buildCandidateHref } from "$lib/campaign-finance-detail/contract";
import { formatCurrency } from "$lib/campaign-finance-detail/presentation";
// US_STATE_OPTIONS is the repo's single owner of USPS-code -> display-spelling
// pairs. The election index reuses it for state group headings rather than
// standing up a second, drift-prone copy of the same map.
import { US_STATE_OPTIONS } from "$lib/campaign-finance-detail/filter-options";
import {
  OFFICE_LEVELS,
  buildCandidacyRoutePath,
  buildContestRoutePath,
  buildElectionDateRoutePath,
  buildOfficeRoutePath,
  buildOfficeholdingRoutePath,
  type CandidacyDetailResponse,
  type CandidacySummary,
  type ContestCandidateMoneyResponse,
  type ContestCandidateMoneyRow,
  type ContestDetailResponse,
  type UpcomingElectionTimelineEntry,
  type ElectionContestSummary,
  type ElectionDateAggregateResponse,
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

export type ContestCandidateFinanceRow = {
  personId: string;
  personName: string;
  personHref: string | null;
  candidateHref: string | null;
  party: string;
  incumbentChallenge: string;
  financeFacts: CivicFactRow[];
  outsideSpendingFacts: CivicFactRow[];
  /** Non-null exactly when this candidacy has no linked FEC candidate record. */
  moneyUnavailableMessage: string | null;
};

/** Answer-first race totals, rendered above the scoreboard. */
export type RaceMoneySummary = {
  candidateCount: number;
  totalRaised: string;
  /**
   * False when no candidate in the race has loaded fundraising. The summary
   * line then states the gap instead of printing "$0.00 raised" about a race
   * whose fundraising nobody has measured. The exact twin of
   * `outsideSpendingKnown` below, on the other dataset in the same response.
   */
  fundraisingKnown: boolean;
  totalOutsideSupport: string;
  totalOutsideOppose: string;
  /**
   * False when no candidate in the race has loaded outside spending. The
   * summary line then states the gap instead of printing "$0.00 supporting",
   * which is the claim that made the most expensive Senate race in US history
   * read as having drawn no outside money at all.
   */
  outsideSpendingKnown: boolean;
  selectedCycle: number;
  /** Set when at least one candidate's money is unknown, qualifying the totals. */
  incompleteNote: string | null;
  /**
   * Set when at least one candidate's outside spending was never loaded, so the
   * support/oppose totals cover only part of the race.
   */
  outsideSpendingNote: string | null;
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
  raceMoneySummary: RaceMoneySummary | null;
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
// Unknown coverage, never zero activity. The screen specs forbid "$0" here:
// "this candidate raised nothing" and "we have not loaded this candidate's
// filings" are different claims and only one of them is true.
const CONTEST_CANDIDATE_MONEY_UNKNOWN_MESSAGE =
  "No FEC candidate record is linked for this candidacy, so Civibus has not loaded " +
  "fundraising figures for it. This is missing coverage, not zero fundraising.";
const CONTEST_UNKNOWN_MONEY_VALUE = "Not available";
const RACE_OUTSIDE_SPENDING_INCOMPLETE_NOTE =
  "Civibus has not loaded independent-expenditure filings for at least one candidate " +
  "in this race for this cycle, so outside spending shown here is incomplete. This is " +
  "missing coverage, not an absence of outside spending.";
const RACE_MONEY_INCOMPLETE_NOTE =
  "At least one candidate in this race has no linked FEC record, so these race " +
  "totals cover only the candidates Civibus has loaded.";
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
  const withDisambiguator = rows.map((r) => `${prefix} ${r.personName}, ${r.disambiguator}`);
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
    baseRows.map((r) => ({
      personName: r.personName,
      disambiguator: r.holderStatus
    }))
  );

  return baseRows.map((row, i) => ({ ...row, linkAriaLabel: labels[i] }));
}

function buildIncompleteDataWarning(incompleteStates: OfficeIncompleteDataState[]): string | null {
  if (incompleteStates.length === 0) {
    return null;
  }

  return incompleteStates.map((state) => INCOMPLETE_DATA_WARNING_BY_STATE[state]).join(" ");
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
    {
      label: "Number of seats",
      value: formatDisplayValue(detail.number_of_seats)
    }
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
function buildOfficeCurrentHolderCard(
  detail: OfficeDetailResponse
): OfficeCurrentHolderCard | null {
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
    const lowerDiff =
      parseDateSortValue(b.valid_period_lower) - parseDateSortValue(a.valid_period_lower);
    if (lowerDiff !== 0) {
      return lowerDiff;
    }
    const upperDiff =
      parseDateSortValue(b.valid_period_upper) - parseDateSortValue(a.valid_period_upper);
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
/**
 * Office contest rows, in the order the backend selected them.
 *
 * Deliberately does NOT re-sort. The backend picks five rows ordered by
 * distance from today (see _OFFICE_RECENT_CONTESTS_SQL) so the election a
 * reader came for leads the list. Re-sorting by date descending here would put
 * the most distant future contest back on top and silently undo that — the
 * presenter would be overruling a selection it cannot see the rest of.
 */
function buildOfficeRecentContestRows(detail: OfficeDetailResponse): OfficeRecentContestRow[] {
  const rows = Array.isArray(detail.recent_contests) ? [...detail.recent_contests] : [];

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
  winnerCandidacyId: string | null | undefined,
  selectedCycleByPersonId: Record<string, number | null>
): ContestCandidacyRow[] {
  const baseRows = candidacies.map((candidacy) => ({
    id: candidacy.candidacy_id,
    personId: candidacy.person_id,
    personName: candidacy.person_name,
    personHref: appendSelectedCycleToHref(
      buildEntityRouteHref("person", candidacy.person_id),
      selectedCycleByPersonId[candidacy.person_id] ?? null
    ),
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
    {
      label: "Filing deadline",
      value: formatDateValue(detail.filing_deadline)
    },
    { label: "Partisan", value: formatBoolean(detail.is_partisan) },
    {
      label: "Number of seats",
      value: formatDisplayValue(detail.number_of_seats)
    }
  ];
}

function buildContestKeyMetricRows(candidacyRows: ContestCandidacyRow[]): CivicFactRow[] {
  return [{ label: "Candidacies", value: String(candidacyRows.length) }];
}

function appendSelectedCycleToHref(
  href: string | null,
  selectedCycle: number | null
): string | null {
  if (href === null || selectedCycle === null) {
    return href;
  }

  if (/[?&]cycle=/.test(href)) {
    return href;
  }

  const separator = href.includes("?") ? "&" : "?";
  return `${href}${separator}cycle=${selectedCycle}`;
}

/**
 * Read the race's selected cycle from the batched money response.
 *
 * The backend resolves and validates the cycle once for the whole contest, so
 * every candidate on a race page is by construction reporting the same window.
 * The old per-candidate fan-out could not guarantee that.
 */
function getRaceSelectedCycle(
  candidateMoney: ContestCandidateMoneyResponse | null,
  fallbackSelectedCycle: number | null
): number | null {
  return candidateMoney?.selected_cycle ?? fallbackSelectedCycle;
}

/**
 * Money facts for one candidate row.
 *
 * Returns an empty list when the candidacy has no linked FEC candidate row.
 * That is the ONLY signal for unknown coverage — the caller renders explicit
 * unknown copy rather than any figure. Never derive "no money" from the
 * numbers: a real zero and an absent record are different claims, and the
 * screen specs forbid publishing the second as the first.
 */
function buildContestCandidateFinanceFacts(row: ContestCandidateMoneyRow): CivicFactRow[] {
  if (!row.has_fec_money) {
    return [];
  }

  return [
    { label: "Raised", value: formatOptionalContestCurrency(row.total_raised) },
    { label: "Spent", value: formatOptionalContestCurrency(row.total_spent) },
    {
      label: "Cash on hand",
      value: formatOptionalContestCurrency(row.cash_on_hand)
    }
  ];
}

/**
 * Outside-spending facts.
 *
 * A zero here is real *only* when the backend measured it. `ie_support_total`
 * is null when no Schedule E was loaded for the selected cycle, and the two
 * cases must not look alike: rendering "$0.00" for an unloaded cycle told
 * readers the most expensive Senate race in US history drew no outside money.
 */
function buildContestCandidateOutsideSpendingFacts(row: ContestCandidateMoneyRow): CivicFactRow[] {
  return [
    {
      label: "Outside spending supporting",
      value: formatOptionalContestCurrency(row.ie_support_total)
    },
    {
      label: "Outside spending opposing",
      value: formatOptionalContestCurrency(row.ie_oppose_total)
    }
  ];
}

/** Format a nullable money string; null means unknown, and must not read as zero. */
function formatOptionalContestCurrency(value: string | null): string {
  return value === null ? CONTEST_UNKNOWN_MONEY_VALUE : formatCurrency(value);
}

/**
 * Build the candidate href with the same slug-vs-UUID rule the candidate list
 * uses, so a race page never links to a URL the candidate page would not own.
 */
function buildContestCandidateHref(row: ContestCandidateMoneyRow): string | null {
  if (row.candidate_id === null) {
    return null;
  }

  return buildCandidateHref({
    id: row.candidate_id,
    slug: row.candidate_slug ?? "",
    slug_is_unique: row.candidate_slug_is_unique,
    identity_is_safe: row.candidate_identity_is_safe
  });
}

/**
 * The money scoreboard, one row per candidacy, in the backend's order.
 *
 * Order is the backend's (raised desc, unknown last) rather than the candidacy
 * table's alphabetical order: a race page's job is to show who is ahead.
 */
function buildContestCandidateFinanceRows(
  candidateMoney: ContestCandidateMoneyResponse | null,
  selectedCycle: number | null
): ContestCandidateFinanceRow[] {
  if (candidateMoney === null) {
    return [];
  }

  return candidateMoney.rows.map((row) => ({
    personId: row.person_id,
    personName: row.person_name,
    personHref: appendSelectedCycleToHref(
      buildEntityRouteHref("person", row.person_id),
      selectedCycle
    ),
    candidateHref: appendSelectedCycleToHref(buildContestCandidateHref(row), selectedCycle),
    party: formatDisplayValue(row.party),
    incumbentChallenge: formatDisplayValue(row.incumbent_challenge),
    financeFacts: buildContestCandidateFinanceFacts(row),
    outsideSpendingFacts: buildContestCandidateOutsideSpendingFacts(row),
    moneyUnavailableMessage: row.has_fec_money ? null : CONTEST_CANDIDATE_MONEY_UNKNOWN_MESSAGE
  }));
}

/**
 * The answer-first headline race_detail.md specifies.
 *
 * Qualifies itself when any candidate's money is unknown, so a partial total is
 * never presented as the race's complete total.
 */
function buildRaceMoneySummary(
  candidateMoney: ContestCandidateMoneyResponse | null
): RaceMoneySummary | null {
  if (candidateMoney === null || candidateMoney.candidate_count === 0) {
    return null;
  }

  // Null race totals mean no candidate in the race has loaded outside spending,
  // so the headline has to say that in words instead of printing a figure.
  const outsideSpendingKnown = candidateMoney.total_ie_support !== null;
  // Same rule, same response, other dataset: a null fundraising rollup means
  // nothing was loaded for anyone in the race, so there is no figure to print.
  const fundraisingKnown = candidateMoney.total_raised !== null;

  return {
    candidateCount: candidateMoney.candidate_count,
    totalRaised: formatOptionalContestCurrency(candidateMoney.total_raised),
    fundraisingKnown,
    totalOutsideSupport: formatOptionalContestCurrency(candidateMoney.total_ie_support),
    totalOutsideOppose: formatOptionalContestCurrency(candidateMoney.total_ie_oppose),
    outsideSpendingKnown,
    selectedCycle: candidateMoney.selected_cycle,
    // Only a total that exists gets qualified. When nothing is known the
    // headline already says so outright, and adding "these totals cover only
    // the candidates Civibus has loaded" beneath it would imply there were
    // totals. Mirrors outsideSpendingNote below.
    incompleteNote:
      fundraisingKnown && candidateMoney.has_unknown_candidate_money ? RACE_MONEY_INCOMPLETE_NOTE : null,
    // Its own note, not a reuse of incompleteNote: Schedule A and Schedule E
    // load independently, so a race can have complete fundraising and no
    // outside-spending coverage at all, and the reader needs to know which.
    // Only a total that exists gets qualified — when nothing is known the
    // summary line already says so outright, and repeating it as a caveat
    // would read as a second, weaker claim.
    outsideSpendingNote:
      outsideSpendingKnown && candidateMoney.has_unknown_candidate_ie
        ? RACE_OUTSIDE_SPENDING_INCOMPLETE_NOTE
        : null
  };
}

function buildCandidacyFactRows(detail: CandidacyDetailResponse): CivicFactRow[] {
  return [
    { label: "Person", value: detail.person_name },
    { label: "Party", value: formatDisplayValue(detail.party) },
    { label: "Filing date", value: formatDateValue(detail.filing_date) },
    { label: "Status", value: formatDisplayValue(detail.status) },
    {
      label: "Incumbent/challenger",
      value: formatDisplayValue(detail.incumbent_challenge)
    },
    {
      label: "Candidate number",
      value: formatDisplayValue(detail.candidate_number)
    }
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
    {
      label: "Valid through",
      value: formatDateValue(detail.valid_period_upper)
    },
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

export function buildOfficeDetailMetadataFromDetail(
  detail: OfficeDetailResponse
): DetailRouteMetadata {
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

export function buildContestDetailMetadataFromDetail(
  detail: ContestDetailResponse
): DetailRouteMetadata {
  return buildContestDetailMetadata(detail.name, detail.candidacies.length);
}

export function buildCandidacyDetailMetadata(personName: string): DetailRouteMetadata {
  return {
    title: `${personName} | Candidacy | Civibus`,
    description: `Candidacy profile for ${personName}.`
  };
}

export function buildCandidacyDetailMetadataFromDetail(
  detail: CandidacyDetailResponse
): DetailRouteMetadata {
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
export function buildOfficeDetailPresentation(
  detail: OfficeDetailResponse
): OfficeDetailPresentation {
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
  candidateMoney?: ContestCandidateMoneyResponse | null;
  selectedCycle?: number | null;
};

/**
 */
export function buildContestDetailPresentation(
  detail: ContestDetailResponse,
  options?: BuildContestDetailPresentationOptions
): ContestDetailPresentation {
  const candidateMoney = options?.candidateMoney ?? null;
  const selectedCycle = getRaceSelectedCycle(candidateMoney, options?.selectedCycle ?? null);
  // The whole race shares one cycle, so every person link carries the same one.
  const selectedCycleByPersonId: Record<string, number | null> = Object.fromEntries(
    detail.candidacies.map((candidacy) => [candidacy.person_id, selectedCycle])
  );
  const candidacyRows = buildContestCandidacyRows(
    detail.candidacies,
    detail.result_winner_candidacy_id,
    selectedCycleByPersonId
  );
  const financeRows = buildContestCandidateFinanceRows(candidateMoney, selectedCycle);

  const matchedWinnerRow =
    detail.result_winner_candidacy_id === undefined || detail.result_winner_candidacy_id === null
      ? null
      : (candidacyRows.find((row) => row.id === detail.result_winner_candidacy_id) ?? null);
  const resultWinnerPersonName =
    detail.result_winner_person_name ?? matchedWinnerRow?.personName ?? null;
  const resultWinnerPersonHref =
    detail.result_winner_person_id === undefined || detail.result_winner_person_id === null
      ? (matchedWinnerRow?.personHref ?? null)
      : appendSelectedCycleToHref(
          buildEntityRouteHref("person", detail.result_winner_person_id),
          selectedCycle
        );
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
    raceMoneySummary: buildRaceMoneySummary(candidateMoney),
    trustSection: buildTrustSection(detail.sources),
    candidacyEmptyMessage: candidacyRows.length === 0 ? CONTEST_CANDIDACY_EMPTY_MESSAGE : null,
    candidateListWarning: detail.candidate_list_incomplete ? CONTEST_CANDIDATE_LIST_WARNING : null
  };
}

export function buildCandidacyDetailPresentation(
  detail: CandidacyDetailResponse
): CandidacyDetailPresentation {
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

// ---------------------------------------------------------------------------
// Election date race index (`/election/[date]`)
// ---------------------------------------------------------------------------
//
// The election-date aggregate arrives as one flat list — 515 rows on a federal
// general-election date. Rendering it as a flat list of names is unusable, so
// everything the reader needs to navigate it is derived here: a link per row, a
// state grouping, a within-group rank that puts the statewide seat first, and a
// context line naming the seat. Screen spec:
// `docs/reference/screen_specs/election_date.md`.

/** One navigable contest row in the election index. */
export type ElectionContestRow = {
  contestId: string;
  contestName: string;
  contestHref: string;
  linkAriaLabel: string;
  officeLabel: string;
  /** Null when the contest has no electoral division to describe. */
  seatLabel: string | null;
  electionTypeLabel: string;
  candidateCountLabel: string;
  /** Pre-joined `officeLabel · seatLabel · electionTypeLabel · candidateCountLabel`. */
  contextLine: string;
};

/** Contests for one state (or the stateless bucket), in reader order. */
export type ElectionStateGroup = {
  key: string;
  /** Two-letter USPS code, or null for the stateless bucket. */
  stateCode: string | null;
  heading: string;
  contestCountLabel: string;
  rows: ElectionContestRow[];
};

export type ElectionIndexPresentation = {
  date: string;
  totalContestsLabel: string;
  totalCandidaciesLabel: string;
  groups: ElectionStateGroup[];
  isEmpty: boolean;
};

/** Sort key for the stateless bucket, chosen to sort after every state group. */
const ELECTION_UNASSIGNED_GROUP_KEY = "__unassigned__";
const ELECTION_UNASSIGNED_GROUP_HEADING = "Nationwide and unassigned";

const ELECTION_STATE_NAME_BY_CODE: ReadonlyMap<string, string> = new Map(
  US_STATE_OPTIONS.map((option) => [option.code, option.label])
);

/**
 * Display spellings for the canonical federal office names in
 * `domains/civics/constants.py::CANONICAL_FEDERAL_DIRECTORY_OFFICE_NAMES`.
 * Anything outside that set (state and local offices) falls back to the raw
 * `office_name`, because inventing a display spelling for an arbitrary ingest
 * value would misreport the seat.
 */
const ELECTION_OFFICE_LABEL_BY_NAME: Readonly<Record<string, string>> = {
  us_president: "U.S. President",
  us_vice_president: "U.S. Vice President",
  us_senate: "U.S. Senate",
  us_house: "U.S. House",
  us_house_delegate: "U.S. House (delegate)"
};

/**
 * Rank offices the way a reader scans a state: the statewide and national seats
 * first, then the district seats. This is why Senate precedes House even though
 * "us_house" sorts before "us_senate" alphabetically, which is all the SQL
 * ORDER BY can offer.
 */
const ELECTION_OFFICE_RANK_BY_NAME: Readonly<Record<string, number>> = {
  us_president: 0,
  us_vice_president: 1,
  us_senate: 2,
  us_house: 3,
  us_house_delegate: 4
};

const ELECTION_OFFICE_RANK_FALLBACK = 5;

const ELECTION_TYPE_LABEL_BY_TYPE: Readonly<Record<string, string>> = {
  general: "General",
  primary: "Primary",
  runoff: "Runoff",
  special: "Special",
  recall: "Recall"
};

/** Display labels for the division types `civic.electoral_division` allows. */
const ELECTION_DIVISION_LABEL_BY_TYPE: Readonly<Record<string, string>> = {
  congressional_district: "Congressional district",
  state_legislative_upper: "State senate district",
  state_legislative_lower: "State house district",
  county: "County",
  municipal: "Municipal",
  judicial_district: "Judicial district",
  school_district: "School district",
  special_district: "Special district",
  at_large: "At-large",
  statewide: "Statewide"
};

/**
 * Parse a district number for ordering and labelling.
 *
 * FEC-derived rows carry zero-padded strings ("01"), and at-large seats arrive
 * as "00", "0", or null. Returning null for all of those keeps at-large seats
 * out of the numeric ordering and stops the label claiming a "District 0".
 */
function parseElectionDistrictNumber(districtNumber: string | null): number | null {
  if (districtNumber === null) {
    return null;
  }
  const trimmed = districtNumber.trim();
  if (trimmed === "" || !/^\d+$/.test(trimmed)) {
    return null;
  }
  const parsed = Number.parseInt(trimmed, 10);
  return parsed > 0 ? parsed : null;
}

/** Name the seat a contest fills, or null when no division is joined. */
function buildElectionSeatLabel(contest: ElectionContestSummary): string | null {
  const divisionType = contest.electoral_division_type;
  if (divisionType === null) {
    return null;
  }

  const districtNumber = parseElectionDistrictNumber(contest.district_number);
  if (divisionType === "congressional_district") {
    return districtNumber === null ? "At-large district" : `District ${districtNumber}`;
  }

  const divisionLabel = ELECTION_DIVISION_LABEL_BY_TYPE[divisionType] ?? divisionType;
  return districtNumber === null ? divisionLabel : `${divisionLabel} ${districtNumber}`;
}

function buildElectionContestRow(contest: ElectionContestSummary): ElectionContestRow {
  const officeLabel = ELECTION_OFFICE_LABEL_BY_NAME[contest.office_name] ?? contest.office_name;
  const seatLabel = buildElectionSeatLabel(contest);
  const electionTypeLabel =
    ELECTION_TYPE_LABEL_BY_TYPE[contest.election_type] ?? contest.election_type;
  const candidateCountLabel = formatCountLabel(contest.candidate_count, "candidate");

  return {
    contestId: contest.contest_id,
    contestName: contest.name,
    // buildContestRoutePath is the single owner of the /contest/[id] path shape.
    contestHref: buildContestRoutePath(contest.contest_id),
    linkAriaLabel: `View ${contest.name}`,
    officeLabel,
    seatLabel,
    electionTypeLabel,
    candidateCountLabel,
    contextLine: [officeLabel, seatLabel, electionTypeLabel, candidateCountLabel]
      .filter((segment): segment is string => segment !== null)
      .join(" · ")
  };
}

/**
 * The state a contest belongs to.
 *
 * `office.state` is authoritative when set. Some ingest paths leave it null on
 * an office whose electoral division does carry the state (territory delegate
 * seats especially), so the division is the fallback rather than dropping the
 * row into the unassigned bucket.
 */
function resolveElectionStateCode(contest: ElectionContestSummary): string | null {
  const officeState = contest.state?.trim();
  if (officeState !== undefined && officeState !== "") {
    return officeState;
  }
  const divisionState = contest.electoral_division_state?.trim();
  return divisionState !== undefined && divisionState !== "" ? divisionState : null;
}

/**
 * Total order inside a state group: office rank, then district number
 * ascending, then name, then id. The trailing id keeps the order total, so two
 * otherwise-identical rows never swap between renders.
 */
function compareElectionContestRows(
  left: ElectionContestSummary,
  right: ElectionContestSummary
): number {
  const leftRank = ELECTION_OFFICE_RANK_BY_NAME[left.office_name] ?? ELECTION_OFFICE_RANK_FALLBACK;
  const rightRank =
    ELECTION_OFFICE_RANK_BY_NAME[right.office_name] ?? ELECTION_OFFICE_RANK_FALLBACK;
  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }

  // Numeric, not lexicographic: district 2 must precede district 12 whether or
  // not the source zero-padded them. Districtless rows sort after numbered ones.
  const leftDistrict = parseElectionDistrictNumber(left.district_number);
  const rightDistrict = parseElectionDistrictNumber(right.district_number);
  if (leftDistrict !== rightDistrict) {
    if (leftDistrict === null) {
      return 1;
    }
    if (rightDistrict === null) {
      return -1;
    }
    return leftDistrict - rightDistrict;
  }

  const byName = left.name.localeCompare(right.name);
  return byName !== 0 ? byName : left.contest_id.localeCompare(right.contest_id);
}

/**
 * Turn one election-date aggregate into the grouped, linked race index.
 *
 * Pure and total: it never drops a contest, so the rendered row count always
 * equals `aggregate.contests.length` even when a row carries no state, no
 * division, and an office name the federal map does not know.
 */
/** One upcoming election date, with its contests as linked rows. */
export type ElectionCalendarEntry = {
  date: string;
  dateHref: string;
  contestCountLabel: string;
  rows: ElectionContestRow[];
  /** Non-null when the date has no loaded contests yet. */
  emptyMessage: string | null;
};

const ELECTION_CALENDAR_DATE_EMPTY_MESSAGE = "No contests are loaded for this date yet.";

/**
 * The upcoming-election calendar, as linked rows.
 *
 * /calendar sits in the shell navigation and in STATIC_PATHS, so it is the top
 * of the race discovery chain — and it rendered 681 contests as bare text, with
 * no link to a contest and not even a link to the election date's own page.
 * Reuses the same row builder and ordering as the per-date election index so
 * the two surfaces cannot describe the same contest differently.
 *
 * A date whose roster has not loaded keeps its heading rather than being
 * dropped: "an election exists here and filings have not opened" is real
 * information, and hiding the row would read as "no election".
 */
export function buildElectionCalendarPresentation(
  entries: UpcomingElectionTimelineEntry[]
): ElectionCalendarEntry[] {
  return entries.map((entry) => ({
    date: entry.date,
    dateHref: buildElectionDateRoutePath(entry.date),
    contestCountLabel: formatCountLabel(entry.contests.length, "contest"),
    rows: [...entry.contests].sort(compareElectionContestRows).map(buildElectionContestRow),
    emptyMessage: entry.contests.length === 0 ? ELECTION_CALENDAR_DATE_EMPTY_MESSAGE : null
  }));
}

export function buildElectionIndexPresentation(
  aggregate: ElectionDateAggregateResponse
): ElectionIndexPresentation {
  const contestsByStateCode = new Map<string, ElectionContestSummary[]>();
  for (const contest of aggregate.contests) {
    const stateCode = resolveElectionStateCode(contest);
    const key = stateCode ?? ELECTION_UNASSIGNED_GROUP_KEY;
    const bucket = contestsByStateCode.get(key);
    if (bucket === undefined) {
      contestsByStateCode.set(key, [contest]);
    } else {
      bucket.push(contest);
    }
  }

  const groups: ElectionStateGroup[] = [...contestsByStateCode.entries()]
    .map(([key, contests]) => {
      const stateCode = key === ELECTION_UNASSIGNED_GROUP_KEY ? null : key;
      return {
        key,
        stateCode,
        // Territories (GU, PR, VI, AS, MP) have no entry in US_STATE_OPTIONS;
        // showing the raw code beats hiding the group.
        heading:
          stateCode === null
            ? ELECTION_UNASSIGNED_GROUP_HEADING
            : (ELECTION_STATE_NAME_BY_CODE.get(stateCode) ?? stateCode),
        contestCountLabel: formatCountLabel(contests.length, "contest"),
        rows: [...contests].sort(compareElectionContestRows).map(buildElectionContestRow)
      };
    })
    .sort((left, right) => {
      // The stateless bucket always sorts last, whatever its heading spells.
      if (left.stateCode === null) {
        return right.stateCode === null ? 0 : 1;
      }
      if (right.stateCode === null) {
        return -1;
      }
      return left.heading.localeCompare(right.heading);
    });

  return {
    date: aggregate.date,
    totalContestsLabel: `Total contests: ${aggregate.total_contests}`,
    totalCandidaciesLabel: `Total candidacies: ${aggregate.total_candidacies}`,
    groups,
    isEmpty: aggregate.contests.length === 0
  };
}
