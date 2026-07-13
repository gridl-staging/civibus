import { encodeRoutePathSegment, type SourceInfo } from "$lib/entity-detail/contract";

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
  candidate_count: number;
  result_status: string | null;
  winning_person_name: string | null;
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

export const CONGRESS_PAGE_PATH = "/congress";

export function buildCongressMembersPath(): string {
  return "/v1/congress/members";
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

export const CIVIC_ROUTE_PREFIXES = ["/office/", "/contest/", "/candidacy/", "/officeholding/"] as const;
