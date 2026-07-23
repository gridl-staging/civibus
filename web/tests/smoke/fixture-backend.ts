/** Tiny HTTP fixture backend used by browser smoke tests. */
import { createServer } from "node:http";

const { SMOKE_API_HOST, SMOKE_API_PORT } =
  (await import(new URL("./fixtures.ts", import.meta.url).href)) as typeof import("./fixtures");
const { smokeFixtures } =
  (await import(new URL("./fixture-data.ts", import.meta.url).href)) as typeof import("./fixture-data");
const { compareFixtureByCandidateId, compareFixtureById, compareFixtureBySearchQuery } =
  (await import(new URL("./compare-fixtures.ts", import.meta.url).href)) as typeof import("./compare-fixtures");
const { buildDonorSearchResponse } =
  (await import(new URL("./donor_lookup_fixture.ts", import.meta.url).href)) as typeof import("./donor_lookup_fixture");

function writeJson(response: import("node:http").ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(body));
}

type CompareFixtureResponse = {
  status: number;
  body: unknown;
  delayMs?: number;
};

function getCompareSearchResponse(url: URL): CompareFixtureResponse | null {
  if (url.pathname !== "/v1/search" || url.searchParams.get("entity_type") !== "person") {
    return null;
  }

  const fixture = compareFixtureBySearchQuery.get(url.searchParams.get("q") ?? "");
  if (fixture === undefined) {
    return null;
  }

  return {
    status: 200,
    body: [{ entity_type: "person", entity_id: fixture.id, name: fixture.name }]
  };
}

/**
 */
function getComparePersonResponse(url: URL): CompareFixtureResponse | null {
  const match = url.pathname.match(
    /^\/v1\/person\/([^/]+)(?:\/(contribution-insights|top-donors|top-employers))?$/
  );
  if (match === null) {
    return null;
  }

  if (getPersonFixtureById(match[1]) !== null) {
    return null;
  }

  const fixture = compareFixtureById.get(match[1]);
  if (fixture === undefined) {
    return null;
  }

  const resource = match[2];
  if (resource === undefined) {
    return { status: 200, body: fixture.person };
  }
  if (resource === "contribution-insights") {
    const errorStatus = fixture.behavior.contributionInsightsErrorStatus;
    return errorStatus === null
      ? {
          status: 200,
          body: fixture.contributionInsights,
          delayMs: fixture.behavior.contributionInsightsDelayMs
        }
      : { status: errorStatus, body: { detail: "Synthetic compare money failure." } };
  }
  if (resource === "top-donors") {
    return { status: 200, body: fixture.topDonors };
  }
  return { status: 200, body: fixture.topEmployers };
}

function getCompareCandidateListResponse(url: URL): CompareFixtureResponse | null {
  if (url.pathname !== "/v1/candidates") {
    return null;
  }

  const personId = url.searchParams.get("person_id") ?? "";
  if (getPersonFixtureById(personId) !== null) {
    return null;
  }

  const fixture = compareFixtureById.get(personId);
  return fixture === undefined ? null : { status: 200, body: fixture.candidateList };
}

/**
 */
function getCompareCandidateResponse(url: URL): CompareFixtureResponse | null {
  const match = url.pathname.match(
    /^\/v1\/candidates\/([^/]+)(?:\/(summary|independent-expenditures(?:\/summary)?))?$/
  );
  if (match === null) {
    return null;
  }

  if (isStandardCandidateFixtureId(match[1])) {
    return null;
  }

  const fixture = compareFixtureByCandidateId.get(match[1]);
  if (fixture === undefined) {
    return null;
  }

  const resource = match[2];
  if (resource === undefined) {
    return { status: 200, body: fixture.candidate };
  }
  if (resource === "summary") {
    return fixture.candidateSummary === null
      ? { status: fixture.behavior.candidateSummaryStatus, body: { detail: "No candidate summary fixture." } }
      : { status: 200, body: fixture.candidateSummary };
  }
  if (resource === "independent-expenditures/summary") {
    return fixture.independentExpenditureSummary === null
      ? { status: 404, body: { detail: "No independent-expenditure summary fixture." } }
      : { status: 200, body: fixture.independentExpenditureSummary };
  }
  return { status: 200, body: fixture.independentExpenditures };
}

function getCompareFixtureResponse(url: URL): CompareFixtureResponse | null {
  return (
    getCompareSearchResponse(url) ??
    getComparePersonResponse(url) ??
    getCompareCandidateListResponse(url) ??
    getCompareCandidateResponse(url)
  );
}

async function serveCompareFixture(
  url: URL,
  response: import("node:http").ServerResponse
): Promise<boolean> {
  const fixtureResponse = getCompareFixtureResponse(url);
  if (fixtureResponse === null) {
    return false;
  }

  if ((fixtureResponse.delayMs ?? 0) > 0) {
    await new Promise((resolve) => setTimeout(resolve, fixtureResponse.delayMs));
  }
  writeJson(response, fixtureResponse.status, fixtureResponse.body);
  return true;
}

/** Matches the committee transaction requests emitted by the detail page. */
function isCommitteeTransactionsRequest(url: URL): boolean {
  if (url.pathname !== "/v1/transactions") {
    return false;
  }

  const committeeId = url.searchParams.get("committee_id");
  if (getCommitteeFixtureById(committeeId) === null) {
    return false;
  }

  if (url.searchParams.get("limit") !== "25") {
    return false;
  }

  return hasOnlyAllowedQueryParams(url, ["committee_id", "limit", "cycle"]);
}

function hasOnlyAllowedQueryParams(url: URL, allowedKeys: readonly string[]): boolean {
  for (const key of url.searchParams.keys()) {
    if (!allowedKeys.includes(key)) {
      return false;
    }
  }

  return true;
}

function parseOptionalNonNegativeInt(value: string | null): number | null {
  if (value === null) {
    return null;
  }

  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) {
    return null;
  }

  return parsed;
}

function isCandidateListRequest(url: URL): boolean {
  if (url.pathname !== "/v1/candidates") {
    return false;
  }

  return hasOnlyAllowedQueryParams(url, ["state", "office", "person_id", "limit", "offset"]);
}

function isCommitteeListRequest(url: URL): boolean {
  if (url.pathname !== "/v1/committees") {
    return false;
  }

  return hasOnlyAllowedQueryParams(url, ["state", "committee_type", "limit", "offset"]);
}

function isCivicGeometryRequest(url: URL): boolean {
  if (url.pathname !== "/v1/civics/geometry") {
    return false;
  }

  return hasOnlyAllowedQueryParams(url, ["level", "state"]);
}

/**
 */
function getNcCivicGeometryFixture(url: URL): unknown | null {
  if (!isCivicGeometryRequest(url)) {
    return null;
  }

  if (url.searchParams.get("state") !== smokeFixtures.ncCountyDrilldown.stateCode) {
    return null;
  }

  const level = url.searchParams.get("level");
  if (level === "state") {
    return smokeFixtures.ncCountyDrilldown.geometryByLevel.state;
  }
  if (level === "county") {
    return smokeFixtures.ncCountyDrilldown.geometryByLevel.county;
  }
  if (level === "congressional_district") {
    return smokeFixtures.ncCountyDrilldown.geometryByLevel.congressional_district;
  }

  return null;
}

function getNcCountyCampaignFinanceSummary(pathname: string): unknown | null {
  const expectedPath = `/v1/counties/${smokeFixtures.ncCountyDrilldown.stateCode.toLowerCase()}/${smokeFixtures.ncCountyDrilldown.countySlug}/campaign-finance-summary`;
  if (pathname !== expectedPath) {
    return null;
  }

  return smokeFixtures.ncCountyDrilldown.campaignFinanceSummary;
}

type PagedListResponse<TItem> = {
  items: TItem[];
  has_next: boolean;
  offset: number;
  limit: number;
};

type CandidateListItem = (typeof smokeFixtures.candidateList.items)[number];

type CommitteeFixture =
  | (typeof smokeFixtures)["committee"]
  | (typeof smokeFixtures)["committeeFilingsPaged"]
  | (typeof smokeFixtures)["committeeFilingsHighTotal"]
  | (typeof smokeFixtures)["committeeEmpty"]
  | (typeof smokeFixtures)["committeePhl"];
type PersonFixture =
  | (typeof smokeFixtures)["person"]
  | (typeof smokeFixtures)["personNoPortrait"]
  | (typeof smokeFixtures)["congressSecondPerson"]
  | (typeof smokeFixtures)["rosterDurhamPerson"]
  | (typeof smokeFixtures)["rosterNcHousePerson"]
  | (typeof smokeFixtures)["personMissingPortraitField"];

/**
 */
function getCommitteeFixtureById(committeeId: string | null): CommitteeFixture | null {
  if (committeeId === smokeFixtures.committee.id) {
    return smokeFixtures.committee;
  }

  if (committeeId === smokeFixtures.committeeEmpty.id) {
    return smokeFixtures.committeeEmpty;
  }

  if (committeeId === smokeFixtures.committeePhl.id) {
    return smokeFixtures.committeePhl;
  }

  if (committeeId === smokeFixtures.committeeFilingsPaged.id) {
    return smokeFixtures.committeeFilingsPaged;
  }

  if (committeeId === smokeFixtures.committeeFilingsHighTotal.id) {
    return smokeFixtures.committeeFilingsHighTotal;
  }

  return null;
}

function isStandardCandidateFixtureId(candidateId: string): boolean {
  return [
    smokeFixtures.candidate.id,
    smokeFixtures.candidateEmpty.id,
    smokeFixtures.candidateDeviant.id,
    smokeFixtures.candidateAl.id,
    smokeFixtures.candidateGa.id
  ].includes(candidateId);
}

// Per-committee request-count diagnostics for the five committee detail bundle
// subresources. Browser tests reset these before a page load and assert that
// URL-only filing pagination (client-side, no server round trip) leaves every
// counter unchanged. The counts object always exposes all five named keys so a
// renamed or dropped counter fails the browser assertion closed instead of
// silently reading as zero.
type CommitteeSubresource =
  | "detail"
  | "summary"
  | "filings_summary"
  | "independent_expenditures_made"
  | "transactions";

function buildZeroedCommitteeRequestCounts(): Record<CommitteeSubresource, number> {
  return {
    detail: 0,
    summary: 0,
    filings_summary: 0,
    independent_expenditures_made: 0,
    transactions: 0
  };
}

const committeeRequestCounts = new Map<string, Record<CommitteeSubresource, number>>();

function recordCommitteeSubresourceHit(committeeId: string, subresource: CommitteeSubresource): void {
  const counts = committeeRequestCounts.get(committeeId) ?? buildZeroedCommitteeRequestCounts();
  counts[subresource] += 1;
  committeeRequestCounts.set(committeeId, counts);
}

function getCommitteeRequestCounts(committeeId: string): Record<CommitteeSubresource, number> {
  return committeeRequestCounts.get(committeeId) ?? buildZeroedCommitteeRequestCounts();
}

/**
 * Resolves a committee detail bundle subresource to its fixture body and records the hit
 * against the per-committee request-count diagnostics used by the pagination smoke test.
 */
function getCommitteeFixtureResponseByPath(pathname: string): { body: unknown } | null {
  const summaryMatch = pathname.match(/^\/v1\/committees\/([^/]+)\/summary$/);
  if (summaryMatch) {
    const committeeFixture = getCommitteeFixtureById(summaryMatch[1]);
    if (committeeFixture === null) {
      return null;
    }
    recordCommitteeSubresourceHit(summaryMatch[1], "summary");
    return { body: committeeFixture.summary };
  }

  const filingSummaryMatch = pathname.match(/^\/v1\/committees\/([^/]+)\/filings\/summary$/);
  if (filingSummaryMatch) {
    const committeeFixture = getCommitteeFixtureById(filingSummaryMatch[1]);
    if (committeeFixture === null) {
      return null;
    }
    recordCommitteeSubresourceHit(filingSummaryMatch[1], "filings_summary");
    return { body: committeeFixture.filingBreakdown };
  }

  const independentExpendituresMadeMatch = pathname.match(
    /^\/v1\/committees\/([^/]+)\/independent-expenditures-made$/
  );
  if (independentExpendituresMadeMatch) {
    const committeeFixture = getCommitteeFixtureById(independentExpendituresMadeMatch[1]);
    if (committeeFixture === null) {
      return null;
    }
    recordCommitteeSubresourceHit(independentExpendituresMadeMatch[1], "independent_expenditures_made");
    return { body: committeeFixture.independentExpendituresMade };
  }

  const detailMatch = pathname.match(/^\/v1\/committees\/([^/]+)$/);
  if (detailMatch) {
    const committeeFixture = getCommitteeFixtureById(detailMatch[1]);
    if (committeeFixture === null) {
      return null;
    }
    recordCommitteeSubresourceHit(detailMatch[1], "detail");
    return { body: committeeFixture.detail };
  }

  return null;
}

/**
 */
function buildPagedListResponse<TItem>(params: {
  url: URL;
  items: readonly TItem[];
  defaultOffset: number;
  defaultLimit: number;
  applyFilters: (items: TItem[], url: URL) => TItem[];
}): PagedListResponse<TItem> {
  const { url, items, defaultOffset, defaultLimit, applyFilters } = params;
  const offset = parseOptionalNonNegativeInt(url.searchParams.get("offset")) ?? defaultOffset;
  const limit = parseOptionalNonNegativeInt(url.searchParams.get("limit")) ?? defaultLimit;
  const filteredItems = applyFilters([...items], url);
  const pagedItems = filteredItems.slice(offset, offset + limit);

  return {
    items: pagedItems,
    has_next: offset + limit < filteredItems.length,
    offset,
    limit
  };
}

/** Builds the filtered, paginated candidate list fixture response. */
function getCandidatePersonId(candidate: CandidateListItem): string | null {
  if (!("person_id" in candidate)) {
    return null;
  }

  const personId = candidate.person_id;
  return typeof personId === "string" ? personId : null;
}

/** Builds the filtered, paginated candidate list fixture response. */
function buildCandidateListResponse(url: URL): PagedListResponse<CandidateListItem> {
  return buildPagedListResponse({
    url,
    items: smokeFixtures.candidateList.items,
    defaultOffset: smokeFixtures.candidateList.offset,
    defaultLimit: smokeFixtures.candidateList.limit,
    applyFilters: (items, currentUrl) => {
      const stateFilter = currentUrl.searchParams.get("state");
      const officeFilter = currentUrl.searchParams.get("office");
      const personFilter = currentUrl.searchParams.get("person_id");

      return items.filter(
        (item) =>
          (stateFilter === null || item.state === stateFilter) &&
          (officeFilter === null || item.office === officeFilter) &&
          (personFilter === null || getCandidatePersonId(item) === personFilter)
      );
    }
  });
}

/** Builds the filtered, paginated committee list fixture response. */
function buildCommitteeListResponse(url: URL): PagedListResponse<(typeof smokeFixtures.committeeList.items)[number]> {
  return buildPagedListResponse({
    url,
    items: smokeFixtures.committeeList.items,
    defaultOffset: smokeFixtures.committeeList.offset,
    defaultLimit: smokeFixtures.committeeList.limit,
    applyFilters: (items, currentUrl) => {
      const stateFilter = currentUrl.searchParams.get("state");
      const committeeTypeFilter = currentUrl.searchParams.get("committee_type");

      return items.filter(
        (item) =>
          (stateFilter === null || item.state === stateFilter) &&
          (committeeTypeFilter === null || item.committee_type === committeeTypeFilter)
      );
    }
  });
}

/** Decodes slug lookup paths while rejecting empty or malformed segments. */
function decodeBySlugPath(pathname: string, prefix: string): string | null {
  if (!pathname.startsWith(prefix)) {
    return null;
  }

  const encodedSlug = pathname.slice(prefix.length);
  if (encodedSlug === "") {
    return null;
  }

  try {
    return decodeURIComponent(encodedSlug);
  } catch {
    return null;
  }
}

const personFixturesById = new Map<string, PersonFixture>(
  [
    smokeFixtures.person,
    smokeFixtures.personNoPortrait,
    smokeFixtures.congressSecondPerson,
    smokeFixtures.rosterDurhamPerson,
    smokeFixtures.rosterNcHousePerson,
    smokeFixtures.personMissingPortraitField
  ].map((personFixture) => [personFixture.id, personFixture] as const)
);

function getPersonFixtureById(personId: string): PersonFixture | null {
  const personFixture = personFixturesById.get(personId);
  return personFixture ?? null;
}

const server = createServer(async (request, response) => {
  if (request.url === undefined) {
    writeJson(response, 500, { detail: "Fixture backend received a request without a URL." });
    return;
  }

  const url = new URL(request.url, `http://${request.headers.host ?? `${SMOKE_API_HOST}:${SMOKE_API_PORT}`}`);

  if (url.pathname === "/healthz") {
    writeJson(response, 200, { status: "ok" });
    return;
  }

  // Fixture-backend-only diagnostics for the committee detail bundle request counts.
  // Reset clears every committee's counters; the read path returns all five named
  // counters for one committee so the pagination smoke test can prove URL-only filing
  // navigation triggered no server-side refetch.
  if (url.pathname === "/_smoke/request-counts/reset") {
    committeeRequestCounts.clear();
    writeJson(response, 200, { ok: true });
    return;
  }

  if (url.pathname === "/_smoke/request-counts") {
    const committeeId = url.searchParams.get("committee_id");
    if (committeeId === null) {
      writeJson(response, 400, {
        detail: "request-counts requires a committee_id query parameter."
      });
      return;
    }
    writeJson(response, 200, {
      committee_id: committeeId,
      counts: getCommitteeRequestCounts(committeeId)
    });
    return;
  }

  if (await serveCompareFixture(url, response)) {
    return;
  }

  const ncCivicGeometryFixture = getNcCivicGeometryFixture(url);
  if (ncCivicGeometryFixture !== null) {
    writeJson(response, 200, ncCivicGeometryFixture);
    return;
  }

  const ncCountyCampaignFinanceSummary = getNcCountyCampaignFinanceSummary(url.pathname);
  if (ncCountyCampaignFinanceSummary !== null) {
    writeJson(response, 200, ncCountyCampaignFinanceSummary);
    return;
  }

  if (url.pathname === "/v1/geometry" && url.searchParams.get("level") === "country" && url.searchParams.size === 1) {
    writeJson(response, 200, smokeFixtures.landingMap.geometry);
    return;
  }

  if (url.pathname === "/v1/campaign-finance/states/summary" && url.searchParams.size === 0) {
    writeJson(response, 200, smokeFixtures.landingMap.summaries);
    return;
  }

  if (url.pathname === "/v1/coverage/registry" && url.searchParams.size === 0) {
    writeJson(response, 200, smokeFixtures.coverageRegistry);
    return;
  }

  if (url.pathname === "/v1/data-sources" && url.searchParams.size === 0) {
    writeJson(response, 200, smokeFixtures.dataSourcesMetadata);
    return;
  }

  if (url.pathname === "/v1/elections/timeline/upcoming" && url.searchParams.size === 0) {
    writeJson(response, 200, smokeFixtures.upcomingElectionTimeline);
    return;
  }

  if (url.pathname === "/v1/congress/members" && url.searchParams.size === 0) {
    writeJson(response, 200, smokeFixtures.congressMembers);
    return;
  }

  if (url.pathname === "/v1/congress/money-summaries" && url.searchParams.size === 0) {
    writeJson(response, 200, smokeFixtures.congressMoneySummaries);
    return;
  }

  const donorSearchResponse = buildDonorSearchResponse(url);
  if (donorSearchResponse !== null) {
    writeJson(response, 200, donorSearchResponse);
    return;
  }

  const electionDateAggregateMatch = url.pathname.match(/^\/v1\/elections\/(\d{4}-\d{2}-\d{2})$/);
  if (electionDateAggregateMatch && electionDateAggregateMatch[1] === smokeFixtures.electionDateAggregate.date) {
    writeJson(response, 200, smokeFixtures.electionDateAggregate);
    return;
  }

  const stateDetailMatch = url.pathname.match(/^\/v1\/campaign-finance\/states\/([A-Z]{2})$/);
  if (stateDetailMatch) {
    const stateCode = stateDetailMatch[1] as keyof typeof smokeFixtures.stateDetails;
    const detail = smokeFixtures.stateDetails[stateCode];
    if (detail) {
      writeJson(response, 200, detail);
      return;
    }
    writeJson(response, 404, { detail: "State not found" });
    return;
  }

  if (
    url.pathname === "/v1/search" &&
    url.searchParams.get("q") === smokeFixtures.search.query &&
    url.searchParams.get("entity_type") === smokeFixtures.search.entityType
  ) {
    writeJson(response, 200, smokeFixtures.search.results);
    return;
  }

  if (
    url.pathname === "/v1/search" &&
    url.searchParams.get("q") === smokeFixtures.searchValidation.query &&
    url.searchParams.get("entity_type") === smokeFixtures.searchValidation.entityType
  ) {
    writeJson(response, smokeFixtures.searchValidation.status, {
      detail: smokeFixtures.searchValidation.detail
    });
    return;
  }

  if (
    url.pathname === "/v1/search" &&
    url.searchParams.get("q") === smokeFixtures.searchSlow.query &&
    url.searchParams.get("entity_type") === smokeFixtures.searchSlow.entityType
  ) {
    await new Promise((resolve) => setTimeout(resolve, smokeFixtures.searchSlow.delayMs));
    writeJson(response, 200, smokeFixtures.searchSlow.results);
    return;
  }

  if (
    url.pathname === "/v1/search" &&
    url.searchParams.get("q") === smokeFixtures.searchCandidate.query &&
    url.searchParams.get("entity_type") === smokeFixtures.searchCandidate.entityType
  ) {
    writeJson(response, 200, smokeFixtures.searchCandidate.results);
    return;
  }

  if (
    url.pathname === "/v1/search" &&
    url.searchParams.get("q") === smokeFixtures.searchContest.query &&
    url.searchParams.get("entity_type") === smokeFixtures.searchContest.entityType
  ) {
    writeJson(response, 200, smokeFixtures.searchContest.results);
    return;
  }

  const candidateSlug = decodeBySlugPath(url.pathname, "/v1/candidates/by-slug/");
  if (candidateSlug !== null) {
    const candidateSlugLookups = smokeFixtures.slugLookups.candidates as Record<string, unknown>;
    writeJson(response, 200, candidateSlugLookups[candidateSlug] ?? []);
    return;
  }

  const committeeSlug = decodeBySlugPath(url.pathname, "/v1/committees/by-slug/");
  if (committeeSlug !== null) {
    const committeeSlugLookups = smokeFixtures.slugLookups.committees as Record<string, unknown>;
    writeJson(response, 200, committeeSlugLookups[committeeSlug] ?? []);
    return;
  }

  if (isCandidateListRequest(url)) {
    writeJson(response, 200, buildCandidateListResponse(url));
    return;
  }

  if (isCommitteeListRequest(url)) {
    writeJson(response, 200, buildCommitteeListResponse(url));
    return;
  }

  const personDetailMatch = url.pathname.match(/^\/v1\/person\/([^/]+)$/);
  if (personDetailMatch) {
    const personFixture = getPersonFixtureById(personDetailMatch[1]);
    if (personFixture !== null) {
      writeJson(response, 200, personFixture.detail);
      return;
    }
  }

  const personContributionInsightsMatch = url.pathname.match(/^\/v1\/person\/([^/]+)\/contribution-insights$/);
  if (personContributionInsightsMatch) {
    const personFixture = getPersonFixtureById(personContributionInsightsMatch[1]);
    if (personFixture !== null && "contributionInsights" in personFixture) {
      writeJson(response, 200, personFixture.contributionInsights);
      return;
    }
    writeJson(response, 404, { detail: "Contribution insights fixture not found." });
    return;
  }

  const personTopDonorsMatch = url.pathname.match(/^\/v1\/person\/([^/]+)\/top-donors$/);
  if (personTopDonorsMatch) {
    const personFixture = getPersonFixtureById(personTopDonorsMatch[1]);
    if (personFixture !== null && "topDonors" in personFixture) {
      writeJson(response, 200, personFixture.topDonors);
      return;
    }
    writeJson(response, 404, { detail: "Person top donors fixture not found." });
    return;
  }

  const personTopEmployersMatch = url.pathname.match(/^\/v1\/person\/([^/]+)\/top-employers$/);
  if (personTopEmployersMatch) {
    const personFixture = getPersonFixtureById(personTopEmployersMatch[1]);
    if (personFixture !== null && "topEmployers" in personFixture) {
      writeJson(response, 200, personFixture.topEmployers);
      return;
    }
    writeJson(response, 404, { detail: "Person top employers fixture not found." });
    return;
  }

  if (url.pathname === `/v1/org/${smokeFixtures.org.id}`) {
    writeJson(response, 200, smokeFixtures.org.detail);
    return;
  }

  const committeeFixtureResponse = getCommitteeFixtureResponseByPath(url.pathname);
  if (committeeFixtureResponse !== null) {
    writeJson(response, 200, committeeFixtureResponse.body);
    return;
  }

  if (isCommitteeTransactionsRequest(url)) {
    const committeeId = url.searchParams.get("committee_id");
    const committeeFixture = getCommitteeFixtureById(committeeId);
    if (committeeFixture === null) {
      writeJson(response, 400, { detail: "Missing committee fixture for committee transaction request." });
      return;
    }
    recordCommitteeSubresourceHit(committeeId as string, "transactions");
    writeJson(
      response,
      200,
      committeeFixture.transactions
    );
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidate.id}/independent-expenditures/summary`) {
    writeJson(response, 200, smokeFixtures.candidate.ieSummary);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidate.id}/independent-expenditures`) {
    writeJson(response, 200, smokeFixtures.candidate.ieTransactions);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidate.id}/summary`) {
    writeJson(response, 200, smokeFixtures.candidate.summary);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidate.id}`) {
    writeJson(response, 200, smokeFixtures.candidate.detail);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidateEmpty.id}/summary`) {
    writeJson(response, 200, smokeFixtures.candidateEmpty.summary);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidateEmpty.id}`) {
    writeJson(response, 200, smokeFixtures.candidateEmpty.detail);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidateDeviant.id}/summary`) {
    writeJson(response, 200, smokeFixtures.candidateDeviant.summary);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidateDeviant.id}`) {
    writeJson(response, 200, smokeFixtures.candidateDeviant.detail);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidateAl.id}/summary`) {
    writeJson(response, 200, smokeFixtures.candidateAl.summary);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidateAl.id}`) {
    writeJson(response, 200, smokeFixtures.candidateAl.detail);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidateGa.id}/summary`) {
    writeJson(response, 200, smokeFixtures.candidateGa.summary);
    return;
  }

  if (url.pathname === `/v1/candidates/${smokeFixtures.candidateGa.id}`) {
    writeJson(response, 200, smokeFixtures.candidateGa.detail);
    return;
  }

  if (url.pathname === `/v1/parcels/${smokeFixtures.property.id}`) {
    writeJson(response, 200, smokeFixtures.property.detail);
    return;
  }

  if (url.pathname === `/v1/parcels/${smokeFixtures.propertyEmpty.id}`) {
    writeJson(response, 200, smokeFixtures.propertyEmpty.detail);
    return;
  }

  if (url.pathname === `/v1/offices/${smokeFixtures.office.id}`) {
    writeJson(response, 200, smokeFixtures.office.detail);
    return;
  }

  if (url.pathname === `/v1/offices/${smokeFixtures.officeEmpty.id}`) {
    writeJson(response, 200, smokeFixtures.officeEmpty.detail);
    return;
  }

  if (url.pathname === `/v1/contests/${smokeFixtures.contest.id}`) {
    writeJson(response, 200, smokeFixtures.contest.detail);
    return;
  }

  if (url.pathname === `/v1/candidacies/${smokeFixtures.candidacy.id}`) {
    writeJson(response, 200, smokeFixtures.candidacy.detail);
    return;
  }

  if (url.pathname === `/v1/officeholdings/${smokeFixtures.officeholding.id}`) {
    writeJson(response, 200, smokeFixtures.officeholding.detail);
    return;
  }

  writeJson(response, 404, {
    detail: `Unhandled smoke fixture request: ${url.pathname}${url.search}`
  });
});

function shutdown(signal: NodeJS.Signals): void {
  server.close(() => {
    process.exit(signal === "SIGINT" ? 130 : 0);
  });
}

server.listen(SMOKE_API_PORT, SMOKE_API_HOST, () => {
  console.log(`Smoke fixture backend listening on ${SMOKE_API_HOST}:${SMOKE_API_PORT}`);
});

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
