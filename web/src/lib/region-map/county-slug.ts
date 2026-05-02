const COUNTY_DIVISION_PREFIX_SEPARATOR = "_county_";

/**
 * Extracts county route slug from canonical civic division names like "nc_county_wake".
 */
export function extractCountySlugFromDivisionName(
  divisionName: string,
  stateCode: string
): string | null {
  const normalizedStateCode = stateCode.trim().toLowerCase();
  if (normalizedStateCode === "") {
    return null;
  }

  const normalizedDivisionName = divisionName.trim().toLowerCase();
  const expectedPrefix = `${normalizedStateCode}${COUNTY_DIVISION_PREFIX_SEPARATOR}`;
  if (!normalizedDivisionName.startsWith(expectedPrefix)) {
    return null;
  }

  const countySlug = normalizedDivisionName.slice(expectedPrefix.length);
  return countySlug === "" ? null : countySlug;
}

export function buildCountyDetailPathFromDivisionName(
  divisionName: string,
  stateCode: string
): string | null {
  const countySlug = extractCountySlugFromDivisionName(divisionName, stateCode);
  if (countySlug === null) {
    return null;
  }

  return `/state/${encodeURIComponent(stateCode.toUpperCase())}/county/${encodeURIComponent(countySlug)}`;
}
