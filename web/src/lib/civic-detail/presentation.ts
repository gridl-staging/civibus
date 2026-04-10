/** View-model builders for civic detail pages and their record tables. */
import { formatCountLabel } from "$lib/count-label";
import { formatBoolean, formatDisplayValue } from "$lib/detail-format";
import {
  buildTrustSection,
  type TrustSectionViewModel
} from "$lib/detail-trust/presentation";
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import type {
  CandidacyDetailResponse,
  CandidacySummary,
  ContestDetailResponse,
  OfficeDetailResponse,
  OfficeIncompleteDataState,
  OfficeholderSummary,
  OfficeholdingDetailResponse
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
};

export type ContestCandidacyRow = {
  id: string;
  personName: string;
  personHref: string | null;
  party: string;
  status: string;
  incumbentChallenge: string;
};

export type OfficeDetailPresentation = {
  title: string;
  sectionOrder: CivicFullSectionKey[];
  factRows: CivicFactRow[];
  keyMetricRows: CivicFactRow[];
  officeholderRows: OfficeholderRow[];
  trustSection: TrustSectionViewModel;
  officeholderEmptyMessage: string | null;
  incompleteDataWarning: string | null;
};

export type ContestDetailPresentation = {
  title: string;
  sectionOrder: CivicFullSectionKey[];
  factRows: CivicFactRow[];
  keyMetricRows: CivicFactRow[];
  candidacyRows: ContestCandidacyRow[];
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
  trustSection: TrustSectionViewModel;
  statusEmptyMessage: string | null;
};

export type OfficeholdingDetailPresentation = {
  title: string;
  sectionOrder: CivicCompactSectionKey[];
  factRows: CivicFactRow[];
  keyMetricRows: CivicFactRow[];
  personHref: string | null;
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
const CONTEST_CANDIDACY_EMPTY_MESSAGE =
  "No candidacies are linked yet. Check back after the next records refresh.";
const CONTEST_CANDIDATE_LIST_WARNING = "Candidate list coverage is incomplete for this contest.";
const CANDIDACY_STATUS_EMPTY_MESSAGE = "Status is not available for this candidacy yet.";
const OFFICEHOLDING_PERIOD_EMPTY_MESSAGE =
  "No valid-period bounds are available for this officeholding.";

function formatDateValue(value: string | null): string {
  if (!value) {
    return "—";
  }

  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    return value.slice(0, 10);
  }

  return value;
}

function buildOfficeholderRows(officeholders: OfficeholderSummary[]): OfficeholderRow[] {
  return officeholders.map((officeholder) => ({
    id: officeholder.officeholding_id,
    personName: officeholder.person_name,
    holderStatus: officeholder.holder_status,
    personHref: buildEntityRouteHref("person", officeholder.person_id)
  }));
}

function buildIncompleteDataWarning(incompleteStates: OfficeIncompleteDataState[]): string | null {
  if (incompleteStates.length === 0) {
    return null;
  }

  return incompleteStates
    .map((state) => INCOMPLETE_DATA_WARNING_BY_STATE[state])
    .join(" ");
}

function buildOfficeFactRows(detail: OfficeDetailResponse): CivicFactRow[] {
  return [
    { label: "Name", value: detail.name },
    { label: "Title", value: formatDisplayValue(detail.title) },
    { label: "Office level", value: detail.office_level },
    { label: "State", value: formatDisplayValue(detail.state) },
    { label: "Elected", value: formatBoolean(detail.is_elected) },
    { label: "Number of seats", value: formatDisplayValue(detail.number_of_seats) }
  ];
}

function buildOfficeKeyMetricRows(officeholderRows: OfficeholderRow[]): CivicFactRow[] {
  return [{ label: "Current officeholders", value: String(officeholderRows.length) }];
}

function buildContestCandidacyRows(candidacies: CandidacySummary[]): ContestCandidacyRow[] {
  return candidacies.map((candidacy) => ({
    id: candidacy.candidacy_id,
    personName: candidacy.person_name,
    personHref: buildEntityRouteHref("person", candidacy.person_id),
    party: formatDisplayValue(candidacy.party),
    status: formatDisplayValue(candidacy.status),
    incumbentChallenge: formatDisplayValue(candidacy.incumbent_challenge)
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

export function buildOfficeDetailPresentation(detail: OfficeDetailResponse): OfficeDetailPresentation {
  const officeholderRows = buildOfficeholderRows(detail.current_officeholders);

  return {
    title: detail.name,
    sectionOrder: CIVIC_FULL_SECTION_ORDER,
    factRows: buildOfficeFactRows(detail),
    keyMetricRows: buildOfficeKeyMetricRows(officeholderRows),
    officeholderRows,
    trustSection: buildTrustSection(detail.sources),
    officeholderEmptyMessage: officeholderRows.length === 0 ? OFFICEHOLDER_EMPTY_MESSAGE : null,
    incompleteDataWarning: buildIncompleteDataWarning(detail.incomplete_data_states)
  };
}

export function buildContestDetailPresentation(detail: ContestDetailResponse): ContestDetailPresentation {
  const candidacyRows = buildContestCandidacyRows(detail.candidacies);

  return {
    title: detail.name,
    sectionOrder: CIVIC_FULL_SECTION_ORDER,
    factRows: buildContestFactRows(detail),
    keyMetricRows: buildContestKeyMetricRows(candidacyRows),
    candidacyRows,
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
    trustSection: buildTrustSection(detail.sources),
    validPeriodEmptyMessage:
      detail.valid_period_lower === null && detail.valid_period_upper === null
        ? OFFICEHOLDING_PERIOD_EMPTY_MESSAGE
        : null
  };
}
