export const DONOR_SEARCH_API_PATH = '/v1/donors/search';
export const DONOR_SEARCH_PAGE_PATH = '/donors';
export const DONOR_SEARCH_MIN_QUERY_LEN = 3;
export const DONOR_SEARCH_MAX_LIMIT = 50;
export const DONOR_SEARCH_BY_MODES = ['name', 'employer', 'zip'] as const;

export type DonorSearchByMode = (typeof DONOR_SEARCH_BY_MODES)[number];

export type SourceInfo = {
  domain: string;
  jurisdiction?: string | null;
  data_source_name: string;
  data_source_url: string;
  source_record_key?: string | null;
  record_url?: string | null;
  pull_date: string;
};

export type DonorSearchSourceInfo = SourceInfo;

export type DonorSearchRecipient = {
  person_id: string;
  candidate_id: string;
  fec_candidate_id: string;
  candidate_name: string;
  committee_id: string;
  fec_committee_id: string;
  committee_name: string;
  total_amount: string;
  transaction_count: number;
};

export type DonorSearchResult = {
  id: string;
  contributor_name: string;
  contributor_employer?: string | null;
  contributor_occupation?: string | null;
  contributor_city?: string | null;
  contributor_state?: string | null;
  normalized_zip5?: string | null;
  total_amount: string;
  transaction_count: number;
  latest_transaction_date?: string | null;
  recipients: DonorSearchRecipient[];
  sources: DonorSearchSourceInfo[];
};

export type DonorSearchResponse = {
  query: string;
  by: DonorSearchByMode;
  limit: number;
  offset: number;
  results: DonorSearchResult[];
};

export type DonorSearchPathParams = {
  q: string;
  by?: string | null;
  limit?: number | string | null;
  offset?: number | string | null;
};

export type DonorSearchPagePathParams = {
  q?: string | null;
  by?: string | null;
  limit?: number | string | null;
  offset?: number | string | null;
};

function hasQueryParamValue(query: DonorSearchPagePathParams['q']): query is string {
  return query !== undefined && query !== null && query !== '';
}

function hasParamValue(value: string | number | null | undefined): value is string | number {
  return value !== undefined && value !== null && value !== '';
}

function buildDonorQueryParams(
  params: DonorSearchPagePathParams,
  includeEmptyQuery: boolean
): URLSearchParams {
  const searchParams = new URLSearchParams();

  if (includeEmptyQuery || hasQueryParamValue(params.q)) {
    searchParams.set('q', params.q ?? '');
  }

  if (hasParamValue(params.by)) {
    searchParams.set('by', String(params.by));
  }

  if (hasParamValue(params.limit)) {
    searchParams.set('limit', String(params.limit));
  }

  if (hasParamValue(params.offset)) {
    searchParams.set('offset', String(params.offset));
  }

  return searchParams;
}

export function isDonorSearchByMode(value: string): value is DonorSearchByMode {
  return DONOR_SEARCH_BY_MODES.includes(value as DonorSearchByMode);
}

export function hasDonorShortNameQueryGuidance(q: string, by: string): boolean {
  const trimmedQueryLength = q.trim().length;

  return (
    (by === 'name' || by === 'employer') &&
    trimmedQueryLength >= 1 &&
    trimmedQueryLength < DONOR_SEARCH_MIN_QUERY_LEN
  );
}

export function buildDonorSearchPath(params: DonorSearchPathParams): string {
  const searchParams = buildDonorQueryParams(params, true);
  return `${DONOR_SEARCH_API_PATH}?${searchParams.toString()}`;
}

export function buildDonorPagePath(params: DonorSearchPagePathParams): string {
  const searchParams = buildDonorQueryParams(params, false);
  const query = searchParams.toString();

  if (query === '') {
    return DONOR_SEARCH_PAGE_PATH;
  }

  return `${DONOR_SEARCH_PAGE_PATH}?${query}`;
}
