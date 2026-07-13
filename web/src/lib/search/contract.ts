/**
 * Search routing and validation helpers shared by the search page and API client.
 * The key contract here is that candidate search hits route to canonical person pages.
 */
export const SEARCH_API_PATH = '/v1/search';
export const SEARCH_PAGE_PATH = '/search';
export const SEARCH_QUERY_MIN_LENGTH = 2;
export const SEARCH_ENTITY_TYPES = ['person', 'org', 'committee', 'candidate', 'office', 'contest'] as const;

export type SearchEntityType = (typeof SEARCH_ENTITY_TYPES)[number];
type SearchRouteSegment = 'person' | 'org' | 'committee' | 'office' | 'contest';

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
};

export type SearchPagePathParams = {
  q?: string | null;
  entityType?: string | null;
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SEARCH_ROUTE_SEGMENT_BY_ENTITY_TYPE: Record<SearchEntityType, SearchRouteSegment> = {
  person: 'person',
  org: 'org',
  committee: 'committee',
  // backend candidate search rows are keyed by canonical person UUIDs.
  candidate: 'person',
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
  params: SearchPagePathParams,
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
  return `${SEARCH_API_PATH}?${searchParams.toString()}`;
}

export function buildSearchPagePath(params: SearchPagePathParams): string {
  const searchParams = buildSearchQueryParams(params, false);
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
