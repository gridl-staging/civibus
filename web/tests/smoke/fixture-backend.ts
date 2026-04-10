/** Tiny HTTP fixture backend used by browser smoke tests. */
import { createServer } from "node:http";

const { SMOKE_API_HOST, SMOKE_API_PORT, smokeFixtures } =
  (await import(new URL("./fixtures.ts", import.meta.url).href)) as typeof import("./fixtures");

function writeJson(response: import("node:http").ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(body));
}

/** Matches the committee transaction requests emitted by the detail page. */
function isCommitteeTransactionsRequest(url: URL): boolean {
  if (url.pathname !== "/v1/transactions") {
    return false;
  }

  const committeeId = url.searchParams.get("committee_id");
  if (committeeId !== smokeFixtures.committee.id && committeeId !== smokeFixtures.committeeEmpty.id) {
    return false;
  }

  if (url.searchParams.get("limit") !== "25") {
    return false;
  }

  return url.searchParams.size === 2;
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

  return hasOnlyAllowedQueryParams(url, ["state", "office", "limit", "offset"]);
}

function isCommitteeListRequest(url: URL): boolean {
  if (url.pathname !== "/v1/committees") {
    return false;
  }

  return hasOnlyAllowedQueryParams(url, ["state", "committee_type", "limit", "offset"]);
}

type PagedListResponse<TItem> = {
  items: TItem[];
  has_next: boolean;
  offset: number;
  limit: number;
};

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
function buildCandidateListResponse(url: URL): PagedListResponse<(typeof smokeFixtures.candidateList.items)[number]> {
  return buildPagedListResponse({
    url,
    items: smokeFixtures.candidateList.items,
    defaultOffset: smokeFixtures.candidateList.offset,
    defaultLimit: smokeFixtures.candidateList.limit,
    applyFilters: (items, currentUrl) => {
      const stateFilter = currentUrl.searchParams.get("state");
      const officeFilter = currentUrl.searchParams.get("office");

      return items.filter(
        (item) =>
          (stateFilter === null || item.state === stateFilter) &&
          (officeFilter === null || item.office === officeFilter)
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

const server = createServer((request, response) => {
  if (request.url === undefined) {
    writeJson(response, 500, { detail: "Fixture backend received a request without a URL." });
    return;
  }

  const url = new URL(request.url, `http://${request.headers.host ?? `${SMOKE_API_HOST}:${SMOKE_API_PORT}`}`);

  if (url.pathname === "/healthz") {
    writeJson(response, 200, { status: "ok" });
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

  if (url.pathname === `/v1/person/${smokeFixtures.person.id}`) {
    writeJson(response, 200, smokeFixtures.person.detail);
    return;
  }

  if (url.pathname === `/v1/er/person/${smokeFixtures.person.id}/matches`) {
    writeJson(response, 200, smokeFixtures.person.matches);
    return;
  }

  if (url.pathname === `/v1/graph/person/${smokeFixtures.person.id}/relationships`) {
    writeJson(response, 200, smokeFixtures.person.relationships);
    return;
  }

  if (url.pathname === `/v1/org/${smokeFixtures.org.id}`) {
    writeJson(response, 200, smokeFixtures.org.detail);
    return;
  }

  if (url.pathname === `/v1/er/organization/${smokeFixtures.org.id}/matches`) {
    writeJson(response, 200, smokeFixtures.org.matches);
    return;
  }

  if (url.pathname === `/v1/graph/org/${smokeFixtures.org.id}/relationships`) {
    writeJson(response, 200, smokeFixtures.org.relationships);
    return;
  }

  if (url.pathname === `/v1/committees/${smokeFixtures.committee.id}/summary`) {
    writeJson(response, 200, smokeFixtures.committee.summary);
    return;
  }

  if (url.pathname === `/v1/committees/${smokeFixtures.committee.id}/filings/summary`) {
    writeJson(response, 200, smokeFixtures.committee.filingBreakdown);
    return;
  }

  if (url.pathname === `/v1/committees/${smokeFixtures.committee.id}`) {
    writeJson(response, 200, smokeFixtures.committee.detail);
    return;
  }

  if (isCommitteeTransactionsRequest(url)) {
    const committeeId = url.searchParams.get("committee_id");
    writeJson(
      response,
      200,
      committeeId === smokeFixtures.committee.id
        ? smokeFixtures.committee.transactions
        : smokeFixtures.committeeEmpty.transactions
    );
    return;
  }

  if (url.pathname === `/v1/committees/${smokeFixtures.committeeEmpty.id}/summary`) {
    writeJson(response, 200, smokeFixtures.committeeEmpty.summary);
    return;
  }

  if (url.pathname === `/v1/committees/${smokeFixtures.committeeEmpty.id}/filings/summary`) {
    writeJson(response, 200, smokeFixtures.committeeEmpty.filingBreakdown);
    return;
  }

  if (url.pathname === `/v1/committees/${smokeFixtures.committeeEmpty.id}`) {
    writeJson(response, 200, smokeFixtures.committeeEmpty.detail);
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
