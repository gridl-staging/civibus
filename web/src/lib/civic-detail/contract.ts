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

export type CandidacySummary = {
  candidacy_id: string;
  person_id: string;
  person_name: string;
  party: string | null;
  status: string | null;
  incumbent_challenge: string | null;
};

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
  incomplete_data_states: OfficeIncompleteDataState[];
  sources: SourceInfo[];
};

export type ContestDetailResponse = {
  id: string;
  name: string;
  election_date: string | null;
  election_type: ElectionTypeLiteral;
  office_id: string;
  electoral_division_id: string | null;
  number_of_seats: number;
  filing_deadline: string | null;
  is_partisan: boolean;
  candidate_list_incomplete: boolean;
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
