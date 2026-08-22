import type { SourceInfo } from '$lib/entity-detail/contract';

export const DONOR_SEARCH_API_PATH = '/v1/donors/search';
export const DONOR_SEARCH_PAGE_PATH = '/donors';
export const DONOR_SEARCH_MIN_QUERY_LEN = 3;
export const DONOR_SEARCH_MAX_LIMIT = 50;
export const DONOR_SEARCH_BY_MODES = ['name', 'employer', 'zip'] as const;
export const DONOR_RESOLVED_CONFIDENCE_BANDS = ['match', 'probable_match'] as const;

export type DonorSearchByMode = (typeof DONOR_SEARCH_BY_MODES)[number];
export type DonorResolvedConfidenceBand = (typeof DONOR_RESOLVED_CONFIDENCE_BANDS)[number];

export type DonorSearchRecipient = {
  person_id: string;
  candidate_id: string;
  fec_candidate_id: string;
  // Raw FEC filing string from cf.candidate.name; render through the
  // identity-gated owner (formatCandidatePublicName), never bare.
  candidate_name: string;
  // Whether candidate_name may be promoted into a formatted public identity.
  identity_is_safe: boolean;
  committee_id: string;
  fec_committee_id: string;
  committee_name: string;
  total_amount: string;
  transaction_count: number;
};

export type DonorSearchUnderlyingRecord = {
  donor_identity_id: string;
  contributor_name: string;
  contributor_employer: string | null;
  contributor_occupation: string | null;
  contributor_city: string | null;
  contributor_state: string | null;
  normalized_zip5: string | null;
  sources: SourceInfo[];
};

export type DonorSearchNotCombinedCandidate = DonorSearchUnderlyingRecord & {
  confidence_band: 'possible_match';
};

export type DonorSearchResult = {
  id: string;
  donor_identity_id: string | null;
  contributor_name: string;
  contributor_employer: string | null;
  contributor_occupation: string | null;
  contributor_city: string | null;
  contributor_state: string | null;
  normalized_zip5: string | null;
  total_amount: string;
  transaction_count: number;
  latest_transaction_date: string | null;
  combined_record_count: number;
  confidence_band: DonorResolvedConfidenceBand | null;
  recipients: DonorSearchRecipient[];
  sources: SourceInfo[];
  underlying_records: DonorSearchUnderlyingRecord[];
  not_combined_candidates: DonorSearchNotCombinedCandidate[];
};

export type DonorSearchResponse = {
  query: string;
  by: DonorSearchByMode;
  limit: number;
  offset: number;
  rollup_completed_at: string;
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

type JsonObject = Record<string, unknown>;

function readObject(value: unknown, path: string): JsonObject {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${path} must be an object.`);
  }

  return value as JsonObject;
}

function readArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${path} must be an array.`);
  }

  return value;
}

function assertString(value: unknown, path: string): asserts value is string {
  if (typeof value !== 'string') {
    throw new Error(`${path} must be a string.`);
  }
}

function assertNullableString(value: unknown, path: string): asserts value is string | null {
  if (value !== null && typeof value !== 'string') {
    throw new Error(`${path} must be a string or null.`);
  }
}

function assertInteger(value: unknown, path: string, minimum?: number): asserts value is number {
  if (
    typeof value !== 'number' ||
    !Number.isInteger(value) ||
    (minimum !== undefined && value < minimum)
  ) {
    const minimumDescription = minimum === undefined ? '' : ` greater than or equal to ${minimum}`;
    throw new Error(`${path} must be an integer${minimumDescription}.`);
  }
}

function assertStringFields(value: JsonObject, path: string, fields: readonly string[]): void {
  for (const field of fields) {
    assertString(value[field], `${path}.${field}`);
  }
}

function assertNullableStringFields(
  value: JsonObject,
  path: string,
  fields: readonly string[]
): void {
  for (const field of fields) {
    assertNullableString(value[field], `${path}.${field}`);
  }
}

function assertSourceInfo(value: unknown, path: string, requireFilingUrl: boolean): void {
  const source = readObject(value, path);
  assertStringFields(source, path, [
    'domain',
    'data_source_name',
    'data_source_url',
    'pull_date'
  ]);
  assertNullableStringFields(source, path, [
    'jurisdiction',
    'source_record_key',
    'record_url'
  ]);

  if (requireFilingUrl && !source.record_url) {
    throw new Error(`${path}.record_url must be a non-empty string.`);
  }
}

function assertSourceList(value: unknown, path: string, requireIdentityEvidence: boolean): void {
  const sources = readArray(value, path);
  if (requireIdentityEvidence && sources.length === 0) {
    throw new Error(`${path} must contain at least one source.`);
  }

  sources.forEach((source, index) =>
    assertSourceInfo(source, `${path}[${index}]`, requireIdentityEvidence)
  );
}

function assertDonorSearchRecipient(value: unknown, path: string): void {
  const recipient = readObject(value, path);
  assertStringFields(recipient, path, [
    'person_id',
    'candidate_id',
    'fec_candidate_id',
    'candidate_name',
    'committee_id',
    'fec_committee_id',
    'committee_name',
    'total_amount'
  ]);
  assertInteger(recipient.transaction_count, `${path}.transaction_count`);
  if (typeof recipient.identity_is_safe !== 'boolean') {
    throw new Error(`${path}.identity_is_safe must be a boolean.`);
  }
}

function assertUnderlyingRecord(value: unknown, path: string): void {
  const record = readObject(value, path);
  assertStringFields(record, path, ['donor_identity_id', 'contributor_name']);
  assertNullableStringFields(record, path, [
    'contributor_employer',
    'contributor_occupation',
    'contributor_city',
    'contributor_state',
    'normalized_zip5'
  ]);
  assertSourceList(record.sources, `${path}.sources`, true);
}

function isResolvedConfidenceBand(value: unknown): value is DonorResolvedConfidenceBand {
  return (
    typeof value === 'string' &&
    (DONOR_RESOLVED_CONFIDENCE_BANDS as readonly string[]).includes(value)
  );
}

function assertIdentityTransparency(result: JsonObject, path: string): void {
  const underlyingRecords = readArray(result.underlying_records, `${path}.underlying_records`);
  const candidates = readArray(
    result.not_combined_candidates,
    `${path}.not_combined_candidates`
  );

  underlyingRecords.forEach((record, index) =>
    assertUnderlyingRecord(record, `${path}.underlying_records[${index}]`)
  );
  candidates.forEach((candidate, index) => {
    const candidatePath = `${path}.not_combined_candidates[${index}]`;
    const candidateRecord = readObject(candidate, candidatePath);
    assertUnderlyingRecord(candidateRecord, candidatePath);
    if (candidateRecord.confidence_band !== 'possible_match') {
      throw new Error(`${candidatePath}.confidence_band must be "possible_match".`);
    }
  });

  if (result.donor_identity_id === null) {
    if (
      result.confidence_band !== null ||
      underlyingRecords.length !== 0 ||
      candidates.length !== 0 ||
      result.combined_record_count !== 1
    ) {
      throw new Error(`${path} has invalid unresolved identity evidence.`);
    }
    return;
  }

  if (!isResolvedConfidenceBand(result.confidence_band)) {
    throw new Error(`${path}.confidence_band must be "match" or "probable_match".`);
  }
  if (result.combined_record_count !== underlyingRecords.length) {
    throw new Error(`${path}.combined_record_count must equal underlying_records.length.`);
  }
}

function assertDonorSearchResult(value: unknown, path: string): void {
  const result = readObject(value, path);
  assertStringFields(result, path, ['id', 'contributor_name', 'total_amount']);
  assertNullableStringFields(result, path, [
    'donor_identity_id',
    'contributor_employer',
    'contributor_occupation',
    'contributor_city',
    'contributor_state',
    'normalized_zip5',
    'latest_transaction_date',
    'confidence_band'
  ]);
  assertInteger(result.transaction_count, `${path}.transaction_count`);
  assertInteger(result.combined_record_count, `${path}.combined_record_count`, 1);
  readArray(result.recipients, `${path}.recipients`).forEach((recipient, index) =>
    assertDonorSearchRecipient(recipient, `${path}.recipients[${index}]`)
  );
  assertSourceList(result.sources, `${path}.sources`, false);
  assertIdentityTransparency(result, path);
}

export function assertDonorSearchResponse(
  payload: unknown
): asserts payload is DonorSearchResponse {
  const response = readObject(payload, 'Donor search response');
  assertString(response.query, 'query');
  if (typeof response.by !== 'string' || !isDonorSearchByMode(response.by)) {
    throw new Error('by must be "name", "employer", or "zip".');
  }
  assertInteger(response.limit, 'limit');
  assertInteger(response.offset, 'offset');
  assertString(response.rollup_completed_at, 'rollup_completed_at');
  readArray(response.results, 'results').forEach((result, index) =>
    assertDonorSearchResult(result, `results[${index}]`)
  );
}

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
