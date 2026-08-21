/**
 * Search routing and validation helpers shared by the search page and API client.
 * Every entity type routes to its own canonical detail page; candidate rows are
 * cf.candidate records and route to candidate record pages (civibus-x9d).
 */
export const SEARCH_API_PATH = '/v1/search';
export const SEARCH_PAGE_PATH = '/search';
export const SEARCH_QUERY_MIN_LENGTH = 2;
/**
 * Results per /search page. Pagination follows the /candidates LIMIT+1
 * pattern (`_build_paginated_response` in api/queries/_common.py): the page
 * server requests SEARCH_PAGE_SIZE + 1 rows and treats a returned extra row as
 * "another page exists". The +1 lives client-side because /v1/search returns a
 * bare array rather than the {items, has_next} envelope; folding the envelope
 * into the API is the recorded follow-up, not a second pattern.
 */
export const SEARCH_PAGE_SIZE = 20;
export const SEARCH_ENTITY_TYPES = ['person', 'org', 'committee', 'candidate', 'office', 'contest'] as const;

export type SearchEntityType = (typeof SEARCH_ENTITY_TYPES)[number];
type SearchRouteSegment = 'person' | 'org' | 'committee' | 'candidate' | 'office' | 'contest';

export type SearchApiResultPayload = {
  entity_type: string;
  entity_id: string;
  name: string;
  state?: string | null;
  party?: string | null;
  office_name?: string | null;
  committee_type?: string | null;
  total_raised?: number | string | null;
};

export type SearchApiResult = SearchApiResultPayload & {
  entity_type: SearchEntityType;
};

export type SearchPathParams = {
  q: string;
  entityType?: string | null;
  /** Rows to request; the page server passes SEARCH_PAGE_SIZE + 1. */
  limit?: number;
  /**
   * Raw offset from the page URL, passed through unparsed so backend
   * validation stays authoritative — the same philosophy as `q`.
   */
  offset?: string | number | null;
};

export type SearchPagePathParams = {
  q?: string | null;
  entityType?: string | null;
  /** Page-position offset; omitted when 0 so page one has one canonical URL. */
  offset?: number;
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SEARCH_ROUTE_SEGMENT_BY_ENTITY_TYPE: Record<SearchEntityType, SearchRouteSegment> = {
  person: 'person',
  org: 'org',
  committee: 'committee',
  // civibus-x9d: candidate search rows are cf.candidate records keyed by the
  // candidate UUID, the same unit /candidates browses. The candidate detail
  // route accepts a UUID and canonicalizes to the slug URL when one exists, so
  // this href is always durable — including for records with no person page.
  candidate: 'candidate',
  office: 'office',
  contest: 'contest'
};

function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

function hasEntityTypeFilter(entityType: SearchPathParams["entityType"]): entityType is string {
  return entityType !== undefined && entityType !== null && entityType !== "";
}

function hasSearchQuery(query: SearchPagePathParams['q']): query is string {
  return query !== undefined && query !== null && query !== '';
}

/**
 */
function buildSearchQueryParams(
  // Only the shared q/entity_type pair; each caller appends its own
  // pagination params because the API path and the page path encode them
  // differently (raw passthrough versus canonical positive offset).
  params: { q?: string | null; entityType?: string | null },
  includeEmptyQuery: boolean
): URLSearchParams {
  const searchParams = new URLSearchParams();

  if (includeEmptyQuery || hasSearchQuery(params.q)) {
    searchParams.set('q', params.q ?? '');
  }

  // Only collapse the form's explicit "All types" empty-string sentinel.
  // Any other raw value must pass through unchanged so backend validation stays authoritative.
  if (hasEntityTypeFilter(params.entityType)) {
    searchParams.set('entity_type', params.entityType);
  }

  return searchParams;
}

export function isSearchEntityType(value: string): value is SearchEntityType {
  return SEARCH_ENTITY_TYPES.includes(value as SearchEntityType);
}

export function isRenderableSearchResult(result: SearchApiResultPayload): result is SearchApiResult {
  return isSearchEntityType(result.entity_type) && isUuid(result.entity_id);
}

export function filterRenderableSearchResults(results: SearchApiResultPayload[]): SearchApiResult[] {
  return results.filter(isRenderableSearchResult);
}

export function buildSearchPath(params: SearchPathParams): string {
  const searchParams = buildSearchQueryParams(params, true);

  if (params.limit !== undefined) {
    searchParams.set('limit', String(params.limit));
  }

  // Raw passthrough: junk offsets reach the backend and come back as the same
  // inline 422 validation any other bad search param produces.
  if (params.offset !== undefined && params.offset !== null && params.offset !== '') {
    searchParams.set('offset', String(params.offset));
  }

  return `${SEARCH_API_PATH}?${searchParams.toString()}`;
}

export function buildSearchPagePath(params: SearchPagePathParams): string {
  const searchParams = buildSearchQueryParams(params, false);

  if (params.offset !== undefined && params.offset > 0) {
    searchParams.set('offset', String(params.offset));
  }

  const query = searchParams.toString();

  if (query === '') {
    return SEARCH_PAGE_PATH;
  }

  return `${SEARCH_PAGE_PATH}?${query}`;
}

export function toSearchResultHref(result: Pick<SearchApiResult, 'entity_type' | 'entity_id'>): string {
  if (!isUuid(result.entity_id)) {
    throw new Error('Search result route mapping requires a UUID entity_id.');
  }

  return `/${SEARCH_ROUTE_SEGMENT_BY_ENTITY_TYPE[result.entity_type]}/${result.entity_id}`;
}
