import type { CongressMemberMoneySummary, CongressMemberSummary } from "./contract";
import type { PersonPortraitResponse } from "$lib/entity-detail/contract";
import { sanitizeExternalUrl } from "$lib/url/sanitize-external-url";

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

/**
 */
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
  hasFecMoney: boolean;
  totalRaised: string | null;
  outsideSupport: string | null;
  outsideAgainst: string | null;
  cashOnHand: string | null;
  moneySources: CongressMemberMoneySummary["sources"];
};

export const CONGRESS_MONEY_SORTS = [
  "total_raised",
  "outside_against",
  "outside_support",
  "cash_on_hand"
] as const;

export type CongressMoneySort = (typeof CONGRESS_MONEY_SORTS)[number];

export type CongressDirectoryViewModel = {
  rows: CongressMemberRow[];
  allRowsCount: number;
  activeFilters: CongressDirectoryFilters;
  activeSort: CongressMoneySort;
  chamberOptions: CongressFilterOption[];
  stateOrTerritoryOptions: CongressFilterOption[];
  partyOptions: CongressFilterOption[];
};

const DEFAULT_CONGRESS_MONEY_SORT: CongressMoneySort = "total_raised";

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

function isCongressMoneySort(value: string): value is CongressMoneySort {
  return CONGRESS_MONEY_SORTS.includes(value as CongressMoneySort);
}

function sanitizeSortValue(value: string): CongressMoneySort {
  return isCongressMoneySort(value) ? value : DEFAULT_CONGRESS_MONEY_SORT;
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

function buildMoneySummaryByPersonId(
  moneySummaries: CongressMemberMoneySummary[]
): Map<string, CongressMemberMoneySummary> {
  return new Map(moneySummaries.map((summary) => [summary.person_id, summary]));
}

/**
 */
function buildRowMoney(summary: CongressMemberMoneySummary | undefined): Pick<
  CongressMemberRow,
  "hasFecMoney" | "totalRaised" | "outsideSupport" | "outsideAgainst" | "cashOnHand" | "moneySources"
> {
  if (summary === undefined || !summary.has_fec_money) {
    return {
      hasFecMoney: false,
      totalRaised: null,
      outsideSupport: null,
      outsideAgainst: null,
      cashOnHand: null,
      moneySources: []
    };
  }

  return {
    hasFecMoney: true,
    totalRaised: summary.total_raised,
    outsideSupport: summary.ie_support_total,
    outsideAgainst: summary.ie_oppose_total,
    cashOnHand: summary.cash_on_hand,
    moneySources: summary.sources
  };
}

function parseMoneyMetric(value: string | null): number | null {
  if (value === null) {
    return null;
  }
  const parsedValue = Number(value);
  return Number.isFinite(parsedValue) ? parsedValue : null;
}

export function getCongressMoneyMetric(row: CongressMemberRow, sort: CongressMoneySort): number | null {
  if (sort === "outside_against") {
    return parseMoneyMetric(row.outsideAgainst);
  }
  if (sort === "outside_support") {
    return parseMoneyMetric(row.outsideSupport);
  }
  if (sort === "cash_on_hand") {
    return parseMoneyMetric(row.cashOnHand);
  }
  return parseMoneyMetric(row.totalRaised);
}

function compareRowsByNameThenId(left: CongressMemberRow, right: CongressMemberRow): number {
  const nameComparison = left.personName.localeCompare(right.personName);
  return nameComparison === 0 ? left.id.localeCompare(right.id) : nameComparison;
}

/**
 */
function sortCongressMemberRows(rows: CongressMemberRow[], sort: CongressMoneySort): CongressMemberRow[] {
  return [...rows].sort((left, right) => {
    const leftMetric = getCongressMoneyMetric(left, sort);
    const rightMetric = getCongressMoneyMetric(right, sort);

    if (leftMetric === null && rightMetric === null) {
      return compareRowsByNameThenId(left, right);
    }
    if (leftMetric === null) {
      return 1;
    }
    if (rightMetric === null) {
      return -1;
    }
    if (leftMetric !== rightMetric) {
      return rightMetric - leftMetric;
    }
    return compareRowsByNameThenId(left, right);
  });
}

export function getCongressMoneySourceHref(row: CongressMemberRow): string | null {
  const safeRecordUrl = row.moneySources
    .map((source) => sanitizeExternalUrl(source.record_url))
    .find((url): url is string => url !== null);
  if (safeRecordUrl !== undefined) {
    return safeRecordUrl;
  }

  return row.moneySources
    .map((source) => sanitizeExternalUrl(source.data_source_url))
    .find((url): url is string => url !== null) ?? null;
}

export function buildCongressCompareHref(selectedPersonIds: string[]): string | null {
  const canonicalPersonIds = [...new Set(selectedPersonIds)].sort((left, right) => left.localeCompare(right));
  if (canonicalPersonIds.length < 2 || canonicalPersonIds.length > 4) {
    return null;
  }

  return `/compare?people=${canonicalPersonIds.map((personId) => encodeURIComponent(personId)).join(",")}`;
}

/**
 */
export function buildCongressMemberRow(
  member: CongressMemberSummary,
  moneySummary?: CongressMemberMoneySummary
): CongressMemberRow {
  const stateOrTerritory = member.state ?? "US";
  const party = member.party ?? "Unknown party";
  const contextLabel = formatDistrictOrClass(member);
  const rowMoney = buildRowMoney(moneySummary);

  return {
    id: member.person_id,
    personName: member.person_name,
    personHref: member.person_detail_path,
    chamber: member.chamber,
    stateOrTerritory,
    contextLabel,
    party,
    contextLine: [member.chamber, stateOrTerritory, contextLabel, party].join(" · "),
    portrait: buildPortrait(member.portrait_source_image_url),
    ...rowMoney
  };
}

export function filterCongressMembers(
  members: CongressMemberSummary[],
  filters: CongressDirectoryFilters,
  moneySummaries: CongressMemberMoneySummary[] = []
): CongressMemberRow[] {
  const normalizedFilters = { ...filters, search: normalizeSearchText(filters.search) };
  const moneySummaryByPersonId = buildMoneySummaryByPersonId(moneySummaries);
  return members
    .filter((member) => memberMatchesFilters(member, normalizedFilters))
    .map((member) => buildCongressMemberRow(member, moneySummaryByPersonId.get(member.person_id)));
}

/**
 */
export function buildCongressDirectory(
  members: CongressMemberSummary[],
  filters: Partial<CongressDirectoryFilters>,
  moneySummaries: CongressMemberMoneySummary[] = [],
  sort = ""
): CongressDirectoryViewModel {
  const chamberOptions = uniqueSortedOptions(members.map((member) => member.chamber));
  const stateOrTerritoryOptions = uniqueSortedOptions(members.map((member) => member.state));
  const partyOptions = uniqueSortedOptions(members.map((member) => member.party));
  const activeSort = sanitizeSortValue(sort);
  const activeFilters = {
    ...EMPTY_FILTERS,
    ...filters,
    search: normalizeSearchText(filters.search ?? ""),
    chamber: sanitizeFilterValue(filters.chamber ?? "", optionValues(chamberOptions)),
    state: sanitizeFilterValue(filters.state ?? "", optionValues(stateOrTerritoryOptions)),
    party: sanitizeFilterValue(filters.party ?? "", optionValues(partyOptions))
  };

  return {
    rows: sortCongressMemberRows(filterCongressMembers(members, activeFilters, moneySummaries), activeSort),
    allRowsCount: members.length,
    activeFilters,
    activeSort,
    chamberOptions,
    stateOrTerritoryOptions,
    partyOptions
  };
}
