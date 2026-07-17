const MAX_COMPARE_PEOPLE = 4;
const PEOPLE_QUERY_KEY = "people";
const NOTICE_QUERY_KEY = "notice";

export const COMPARE_NOTICE_VALUES = ["max-4", "unknown-people-dropped"] as const;

export type CompareNotice = (typeof COMPARE_NOTICE_VALUES)[number];

export type NormalizedPeopleQuery = {
  peopleIds: string[];
  notices: CompareNotice[];
  hadPopulatedInput: boolean;
  wasCapped: boolean;
  isCanonicalFor: (peopleIds: readonly string[]) => boolean;
};

function isCompareNotice(value: string): value is CompareNotice {
  return COMPARE_NOTICE_VALUES.includes(value as CompareNotice);
}

function sortNotices(notices: Iterable<CompareNotice>): CompareNotice[] {
  const noticeSet = new Set(notices);
  return COMPARE_NOTICE_VALUES.filter((notice) => noticeSet.has(notice));
}

function parseNotices(searchParams: URLSearchParams): CompareNotice[] {
  const values = searchParams.getAll(NOTICE_QUERY_KEY).flatMap((value) => value.split(","));
  return sortNotices(values.filter(isCompareNotice));
}

export function mergeCompareNotices(
  notices: readonly CompareNotice[],
  additions: readonly CompareNotice[]
): CompareNotice[] {
  return sortNotices([...notices, ...additions]);
}

/**
 */
export function normalizePeopleQuery(searchParams: URLSearchParams): NormalizedPeopleQuery {
  const rawValues = searchParams.getAll(PEOPLE_QUERY_KEY);
  const rawPeopleKey = rawValues.length === 1 ? rawValues[0] : null;
  const normalizedIds = [
    ...new Set(
      rawValues
        .flatMap((value) => value.split(","))
        .map((value) => value.trim())
        .filter((value) => value.length > 0)
    )
  ].sort();

  return {
    peopleIds: normalizedIds.slice(0, MAX_COMPARE_PEOPLE),
    notices: parseNotices(searchParams),
    hadPopulatedInput: rawValues.some((value) => value.trim().length > 0),
    wasCapped: normalizedIds.length > MAX_COMPARE_PEOPLE,
    isCanonicalFor: (peopleIds) =>
      rawPeopleKey !== null && rawPeopleKey === peopleIds.join(",")
  };
}

/**
 */
export function buildCompareUrl(
  peopleIds: readonly string[],
  notices: readonly CompareNotice[] = []
): string {
  const queryParts: string[] = [];
  const normalizedPeopleIds = [...new Set(peopleIds)]
    .filter((personId) => personId.trim().length > 0)
    .sort()
    .slice(0, MAX_COMPARE_PEOPLE);
  if (normalizedPeopleIds.length > 0) {
    queryParts.push(
      `${PEOPLE_QUERY_KEY}=${normalizedPeopleIds.map((personId) => encodeURIComponent(personId)).join(",")}`
    );
  }
  if (notices.length > 0) {
    queryParts.push(`${NOTICE_QUERY_KEY}=${sortNotices(notices).join(",")}`);
  }

  return queryParts.length === 0 ? "/compare" : `/compare?${queryParts.join("&")}`;
}
