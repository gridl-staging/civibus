import { encodeRoutePathSegment, type SourceInfo } from "$lib/entity-detail/contract";
import type {
  CandidateFundraisingCoverage,
  CandidateMoneyCoverage
} from "$lib/campaign-finance-detail/contract";

export const ELECTION_TYPES = ["general", "primary", "runoff", "special", "recall"] as const;

export type ElectionTypeLiteral = (typeof ELECTION_TYPES)[number];

export const DATE_PRECISIONS = ["day", "month", "quarter", "year", "approximate"] as const;

export type DatePrecisionLiteral = (typeof DATE_PRECISIONS)[number];

export const OFFICE_LEVELS = [
  "federal",
  "state",
  "county",
  "municipal",
  "judicial",
  "school_board",
  "special_district"
] as const;

export type OfficeLevel = (typeof OFFICE_LEVELS)[number];

export const OFFICE_INCOMPLETE_DATA_STATES = ["no_officeholder", "no_active_contest"] as const;

export type OfficeIncompleteDataState = (typeof OFFICE_INCOMPLETE_DATA_STATES)[number];

export const OFFICEHOLDING_STATUSES = ["elected", "appointed", "acting", "former"] as const;

export const OFFICEHOLDER_STATUSES = OFFICEHOLDING_STATUSES;

export type OfficeholdingStatusLiteral = (typeof OFFICEHOLDING_STATUSES)[number];

export type OfficeholderStatus = OfficeholdingStatusLiteral;

export type OfficeholderSummary = {
  officeholding_id: string;
  person_id: string;
  person_name: string;
  holder_status: OfficeholderStatus;
};

export type OfficeCurrentHolderCard = {
  officeholding_id: string;
  person_id: string;
  person_name: string;
  holder_status: OfficeholderStatus;
  electoral_division_id: string | null;
  electoral_division_type: string | null;
  electoral_division_state: string | null;
  valid_period_lower: string | null;
  valid_period_upper: string | null;
  date_precision: DatePrecisionLiteral;
};

/**
 */
export type OfficeholdingTimelineRow = {
  officeholding_id: string;
  person_id: string;
  person_name: string;
  holder_status: OfficeholderStatus;
  electoral_division_id: string | null;
  electoral_division_type: string | null;
  electoral_division_state: string | null;
  valid_period_lower: string | null;
  valid_period_upper: string | null;
  date_precision: DatePrecisionLiteral;
  is_active: boolean;
  // Backend-owned ended-state flag. True iff the row's bounded valid_period
  // upper bound has already passed on the server today. Presenters must use
  // this rather than holder_status to decide whether to render ended copy.
  term_ended: boolean;
};

export type OfficeRecentContestSummary = {
  contest_id: string;
  contest_name: string;
  election_date: string | null;
  election_type: ElectionTypeLiteral;
  filing_deadline: string | null;
  electoral_division_id: string | null;
  electoral_division_type: string | null;
  electoral_division_state: string | null;
  is_partisan: boolean;
  candidate_list_incomplete: boolean;
};

export type CandidacySummary = {
  candidacy_id: string;
  person_id: string;
  person_name: string;
  party: string | null;
  status: string | null;
  incumbent_challenge: string | null;
};

/**
 */
export type OfficeDetailResponse = {
  id: string;
  name: string;
  office_level: OfficeLevel;
  title: string | null;
  jurisdiction_id: string | null;
  state: string | null;
  is_elected: boolean;
  number_of_seats: number;
  current_officeholders: OfficeholderSummary[];
  current_holder_card: OfficeCurrentHolderCard | null;
  officeholding_timeline: OfficeholdingTimelineRow[];
  recent_contests: OfficeRecentContestSummary[];
  selected_electoral_division_id: string | null;
  selected_electoral_division_type: string | null;
  selected_electoral_division_state: string | null;
  incomplete_data_states: OfficeIncompleteDataState[];
  sources: SourceInfo[];
};

/**
 */
export type ContestDetailResponse = {
  id: string;
  name: string;
  election_date: string | null;
  election_type: ElectionTypeLiteral;
  office_id: string;
  electoral_division_id: string | null;
  electoral_division_type?: string | null;
  electoral_division_state?: string | null;
  number_of_seats: number;
  filing_deadline: string | null;
  is_partisan: boolean;
  candidate_list_incomplete: boolean;
  result_winner_candidacy_id?: string | null;
  result_winner_person_id?: string | null;
  result_winner_person_name?: string | null;
  candidacies: CandidacySummary[];
  sources: SourceInfo[];
};

/**
 * One candidate's money scoreboard line inside a contest.
 *
 * Money fields are nullable by contract. A candidacy with no matching FEC
 * candidate row has UNKNOWN money, not zero money, and the screen specs forbid
 * rendering unknown coverage as `$0.00`. `has_fec_money === false` is the
 * discriminator; never infer coverage from the numbers themselves.
 */
export type ContestCandidateMoneyRow = {
  candidacy_id: string;
  person_id: string;
  person_name: string;
  party: string | null;
  status: string | null;
  incumbent_challenge: string | null;
  fec_candidate_id: string | null;
  candidate_id: string | null;
  candidate_name: string | null;
  candidate_slug: string | null;
  candidate_slug_is_unique: boolean;
  candidate_identity_is_safe: boolean;
  has_fec_money: boolean;
  total_raised: string | null;
  total_spent: string | null;
  net: string | null;
  cash_on_hand: string | null;
  summary_source: string | null;
  fundraising_coverage: CandidateFundraisingCoverage | null;
  /**
   * Null when no Schedule E was loaded for the selected cycle. "Nothing was
   * spent" and "nothing was loaded" are different claims; only `ie_coverage`
   * says which one a zero here means, and a null must never render as $0.00.
   */
  ie_support_total: string | null;
  ie_oppose_total: string | null;
  ie_support_count: number | null;
  ie_oppose_count: number | null;
  ie_coverage: CandidateMoneyCoverage | null;
};

/**
 * The whole race money scoreboard in one response.
 *
 * Replaces a per-candidacy fan-out of 4N+1 backend calls, which measured ~18s
 * on a 21-candidacy Senate contest and swallowed every failure as "data not
 * yet available".
 */
export type ContestCandidateMoneyResponse = {
  contest_id: string;
  selected_cycle: number;
  candidate_count: number;
  /**
   * Null when no candidate in the race has loaded fundraising. Summing an empty
   * set of known values gives no total, and "Civibus has loaded $0.00 raised"
   * would state a measurement nobody took. A race whose loaded candidates
   * genuinely raised nothing still sends "0.00".
   */
  total_raised: string | null;
  /** Null when no candidate in the race has loaded outside spending. */
  total_ie_support: string | null;
  total_ie_oppose: string | null;
  has_unknown_candidate_money: boolean;
  has_unknown_candidate_ie: boolean;
  rows: ContestCandidateMoneyRow[];
};

export type CandidacyDetailResponse = {
  id: string;
  person_id: string;
  person_name: string;
  contest_id: string;
  party: string | null;
  filing_date: string | null;
  status: string | null;
  incumbent_challenge: string | null;
  candidate_number: string | null;
  sources: SourceInfo[];
};

export type OfficeholdingDetailResponse = {
  id: string;
  person_id: string;
  person_name: string;
  office_id: string;
  electoral_division_id: string | null;
  holder_status: OfficeholdingStatusLiteral;
  valid_period_lower: string | null;
  valid_period_upper: string | null;
  date_precision: DatePrecisionLiteral;
  sources: SourceInfo[];
};

/**
 * One contest row in the `/election/[date]` index and the upcoming timeline.
 *
 * Mirrors `ElectionContestSummary` in `api/models/civics.py`. The
 * `electoral_division_*` and `district_number` fields are the seat context the
 * race index groups and labels by; `electoral_division_id` on its own is a UUID
 * no reader can interpret.
 *
 * `result_status` and `winning_person_name` were removed on 2026-08-17: neither
 * backing query ever selected them, so they were permanently `null` on the wire.
 * Contest results live on `ContestDetailResponse.result_winner_*`.
 */
export type ElectionContestSummary = {
  contest_id: string;
  office_id: string;
  name: string;
  election_type: ElectionTypeLiteral;
  office_name: string;
  office_level: OfficeLevel;
  state: string | null;
  jurisdiction_id: string | null;
  electoral_division_id: string | null;
  electoral_division_type: string | null;
  electoral_division_state: string | null;
  district_number: string | null;
  candidate_count: number;
};

export type ElectionDateAggregateResponse = {
  date: string;
  total_contests: number;
  total_candidacies: number;
  contests: ElectionContestSummary[];
};

export type UpcomingElectionTimelineEntry = {
  date: string;
  contests: ElectionContestSummary[];
};

export type CongressMemberSummary = {
  person_id: string;
  person_name: string;
  officeholding_id: string;
  office_id: string;
  office_name: string;
  chamber: string;
  state: string | null;
  district: string | null;
  district_or_class: string | null;
  party: string | null;
  portrait_source_image_url: string | null;
  person_detail_path: string;
};

/**
 * One seated federal official's money row, as served by
 * `/congress/money-summaries` and by the public JSON/CSV export.
 *
 * Every money field is nullable and null always means UNKNOWN, never zero.
 * `has_fec_money` is a weaker discriminator than it looks: a member can be
 * linked to a real FEC candidate and still have had no Schedule A loaded for
 * the cycle, so `has_fec_money` is true while nothing is known. Read
 * `fundraising_coverage` / `ie_coverage` for that, and never infer coverage
 * from the numbers themselves.
 */
export type CongressMemberMoneySummary = {
  person_id: string;
  person_name: string;
  has_fec_money: boolean;
  candidate_id: string | null;
  /**
   * Null when no Schedule A was loaded for the selected cycle, or when the
   * member has no linked FEC candidate at all. A member whose loaded filings
   * genuinely total nothing still sends "0.00" — that zero is a measurement
   * and must keep rendering as $0.00.
   */
  total_raised: string | null;
  total_spent: string | null;
  net: string | null;
  cash_on_hand: string | null;
  summary_source: string | null;
  /** Present only when the state is not `populated`, so absent means populated. */
  fundraising_coverage?: CandidateFundraisingCoverage | null;
  /** Null when no Schedule E was loaded for the selected cycle. */
  ie_support_total: string | null;
  ie_oppose_total: string | null;
  ie_support_count: number | null;
  ie_oppose_count: number | null;
  ie_coverage?: CandidateMoneyCoverage | null;
  sources: SourceInfo[];
};

export const CONGRESS_PAGE_PATH = "/congress";

export function buildCongressMembersPath(): string {
  return "/v1/congress/members";
}

export function buildCongressMoneySummariesPath(): string {
  return "/v1/congress/money-summaries";
}

export function buildOfficeDetailPath(officeId: string): string {
  return `/v1/offices/${encodeRoutePathSegment(officeId)}`;
}

export function buildOfficeRoutePath(officeId: string): string {
  return `/office/${encodeRoutePathSegment(officeId)}`;
}

export function buildContestDetailPath(contestId: string): string {
  return `/v1/contests/${encodeRoutePathSegment(contestId)}`;
}

export function buildContestCandidateMoneyPath(
  contestId: string,
  request: { cycle?: number } = {}
): string {
  const base = `/v1/contests/${encodeRoutePathSegment(contestId)}/candidate-money`;
  return request.cycle === undefined ? base : `${base}?cycle=${request.cycle}`;
}

export function buildContestRoutePath(contestId: string): string {
  return `/contest/${encodeRoutePathSegment(contestId)}`;
}

export function buildCandidacyDetailPath(candidacyId: string): string {
  return `/v1/candidacies/${encodeRoutePathSegment(candidacyId)}`;
}

export function buildCandidacyRoutePath(candidacyId: string): string {
  return `/candidacy/${encodeRoutePathSegment(candidacyId)}`;
}

export function buildOfficeholdingDetailPath(officeholdingId: string): string {
  return `/v1/officeholdings/${encodeRoutePathSegment(officeholdingId)}`;
}

export function buildOfficeholdingRoutePath(officeholdingId: string): string {
  return `/officeholding/${encodeRoutePathSegment(officeholdingId)}`;
}

export function buildElectionDateAggregatePath(electionDate: string): string {
  return `/v1/elections/${encodeRoutePathSegment(electionDate)}`;
}

export function buildUpcomingElectionTimelinePath(): string {
  return "/v1/elections/timeline/upcoming";
}

export function buildElectionDateRoutePath(electionDate: string): string {
  return `/election/${encodeRoutePathSegment(electionDate)}`;
}

export const CIVIC_ROUTE_PREFIXES = [
  "/office/",
  "/contest/",
  "/candidacy/",
  "/officeholding/"
] as const;
