import type { CongressMemberSummary } from "./contract";
import type { PersonPortraitResponse } from "$lib/entity-detail/contract";

export type CongressDirectoryFilters = {
  search: string;
  chamber: string;
  state: string;
  party: string;
};

export type CongressFilterOption = {
  value: string;
  label: string;
};

export type CongressMemberRow = {
  id: string;
  personName: string;
  personHref: string;
  chamber: string;
  stateOrTerritory: string;
  contextLabel: string;
  party: string;
  contextLine: string;
  portrait: PersonPortraitResponse | null;
};

export type CongressDirectoryViewModel = {
  rows: CongressMemberRow[];
  allRowsCount: number;
  activeFilters: CongressDirectoryFilters;
  chamberOptions: CongressFilterOption[];
  stateOrTerritoryOptions: CongressFilterOption[];
  partyOptions: CongressFilterOption[];
};

const EMPTY_FILTERS: CongressDirectoryFilters = {
  search: "",
  chamber: "",
  state: "",
  party: ""
};

function normalizeSearchText(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function normalizeCompactName(value: string): string {
  return normalizeSearchText(value).replace(/[^a-z0-9]/g, "");
}

function uniqueSortedOptions(values: Array<string | null>): CongressFilterOption[] {
  return [...new Set(values.filter((value): value is string => value !== null && value.trim() !== ""))]
    .sort((left, right) => left.localeCompare(right))
    .map((value) => ({ value, label: value }));
}

function optionValues(options: CongressFilterOption[]): Set<string> {
  return new Set(options.map((option) => option.value));
}

function sanitizeFilterValue(value: string, validValues: Set<string>): string {
  if (value === "") {
    return "";
  }
  return validValues.has(value) ? value : "";
}

function buildPortrait(sourceImageUrl: string | null): PersonPortraitResponse | null {
  if (sourceImageUrl === null) {
    return null;
  }
  return {
    status: "available",
    rights_status: "usable",
    source_image_url: sourceImageUrl,
    mime_type: null,
    width_px: null,
    height_px: null
  };
}

function formatDistrictOrClass(member: CongressMemberSummary): string {
  if (member.district_or_class !== null && member.district_or_class.trim() !== "") {
    if (member.chamber === "House" && /^\d/.test(member.district_or_class)) {
      return `District ${member.district_or_class}`;
    }
    return member.district_or_class;
  }
  if (member.chamber === "Executive") {
    return member.office_name;
  }
  return "At-large";
}

function memberMatchesSearch(member: CongressMemberSummary, search: string): boolean {
  if (search === "") {
    return true;
  }
  const normalizedName = normalizeSearchText(member.person_name);
  const compactName = normalizeCompactName(member.person_name);
  return normalizedName.includes(search) || compactName.includes(normalizeCompactName(search));
}

function memberMatchesFilters(member: CongressMemberSummary, filters: CongressDirectoryFilters): boolean {
  return (
    memberMatchesSearch(member, filters.search) &&
    (filters.chamber === "" || member.chamber === filters.chamber) &&
    (filters.state === "" || member.state === filters.state) &&
    (filters.party === "" || member.party === filters.party)
  );
}

export function buildCongressMemberRow(member: CongressMemberSummary): CongressMemberRow {
  const stateOrTerritory = member.state ?? "US";
  const party = member.party ?? "Unknown party";
  const contextLabel = formatDistrictOrClass(member);

  return {
    id: member.person_id,
    personName: member.person_name,
    personHref: member.person_detail_path,
    chamber: member.chamber,
    stateOrTerritory,
    contextLabel,
    party,
    contextLine: [member.chamber, stateOrTerritory, contextLabel, party].join(" · "),
    portrait: buildPortrait(member.portrait_source_image_url)
  };
}

export function filterCongressMembers(
  members: CongressMemberSummary[],
  filters: CongressDirectoryFilters
): CongressMemberRow[] {
  const normalizedFilters = { ...filters, search: normalizeSearchText(filters.search) };
  return members.filter((member) => memberMatchesFilters(member, normalizedFilters)).map(buildCongressMemberRow);
}

export function buildCongressDirectory(
  members: CongressMemberSummary[],
  filters: Partial<CongressDirectoryFilters>
): CongressDirectoryViewModel {
  const chamberOptions = uniqueSortedOptions(members.map((member) => member.chamber));
  const stateOrTerritoryOptions = uniqueSortedOptions(members.map((member) => member.state));
  const partyOptions = uniqueSortedOptions(members.map((member) => member.party));
  const activeFilters = {
    ...EMPTY_FILTERS,
    ...filters,
    search: normalizeSearchText(filters.search ?? ""),
    chamber: sanitizeFilterValue(filters.chamber ?? "", optionValues(chamberOptions)),
    state: sanitizeFilterValue(filters.state ?? "", optionValues(stateOrTerritoryOptions)),
    party: sanitizeFilterValue(filters.party ?? "", optionValues(partyOptions))
  };

  return {
    rows: filterCongressMembers(members, activeFilters),
    allRowsCount: members.length,
    activeFilters,
    chamberOptions,
    stateOrTerritoryOptions,
    partyOptions
  };
}
