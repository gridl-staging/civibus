import { describe, expect, it } from 'vitest';
import {
  assertDonorSearchResponse,
  buildDonorPagePath,
  buildDonorSearchPath,
  DONOR_SEARCH_BY_MODES,
  DONOR_SEARCH_MAX_LIMIT,
  DONOR_SEARCH_MIN_QUERY_LEN,
  hasDonorShortNameQueryGuidance,
  isDonorSearchByMode
} from './contract';

const source = {
  domain: 'campaign_finance',
  jurisdiction: 'federal/fec',
  data_source_name: 'FEC filing',
  data_source_url: 'https://www.fec.gov/data/',
  source_record_key: 'filing-1',
  record_url: 'https://www.fec.gov/data/receipts/?data_type=processed',
  pull_date: '2026-07-09T12:00:00Z'
};

const unresolvedResult = {
  id: '72000000-0000-0000-0000-000000000101',
  donor_identity_id: null,
  contributor_name: 'JANE SMITH',
  contributor_employer: 'Civibus Labs',
  contributor_occupation: 'Engineer',
  contributor_city: 'Durham',
  contributor_state: 'NC',
  normalized_zip5: '27701',
  total_amount: '500.00',
  transaction_count: 3,
  latest_transaction_date: '2024-07-15',
  combined_record_count: 1,
  confidence_band: null,
  recipients: [],
  sources: [source],
  underlying_records: [],
  not_combined_candidates: []
};

const underlyingRecord = {
  donor_identity_id: '72100000-0000-0000-0000-000000000001',
  contributor_name: 'TRANSPARENT IDENTITY',
  contributor_employer: 'Civibus Labs',
  contributor_occupation: 'Engineer',
  contributor_city: 'Durham',
  contributor_state: 'NC',
  normalized_zip5: '27701',
  sources: [source]
};

const resolvedResult = {
  ...unresolvedResult,
  id: '72100000-0000-0000-0000-000000000101',
  donor_identity_id: '72100000-0000-0000-0000-000000000001',
  contributor_name: 'TRANSPARENT IDENTITY',
  total_amount: '200.00',
  transaction_count: 2,
  latest_transaction_date: '2025-06-02',
  combined_record_count: 2,
  confidence_band: 'match',
  underlying_records: [
    underlyingRecord,
    {
      ...underlyingRecord,
      donor_identity_id: '72100000-0000-0000-0000-000000000002',
      contributor_name: 'TRANSPARENT IDENTITY ALT',
      contributor_employer: 'Open Civic Works',
      contributor_occupation: 'Architect',
      contributor_city: 'Raleigh',
      normalized_zip5: '27601'
    }
  ]
};

const possibleMatchResult = {
  ...resolvedResult,
  confidence_band: 'probable_match',
  not_combined_candidates: [
    {
      ...underlyingRecord,
      donor_identity_id: '72100000-0000-0000-0000-000000000003',
      contributor_name: 'POSSIBLE IDENTITY',
      contributor_occupation: 'Analyst',
      contributor_city: 'Chapel Hill',
      normalized_zip5: '27514',
      confidence_band: 'possible_match',
      sources: [{ ...source }]
    }
  ]
};

const recipient = {
  person_id: '72000000-0000-4000-8000-000000000001',
  candidate_id: '72000000-0000-0000-0000-000000000014',
  fec_candidate_id: 'H0NC01001',
  candidate_name: 'OSSOFF, T. JONATHAN',
  committee_id: '72000000-0000-0000-0000-000000000015',
  fec_committee_id: 'C72000001',
  committee_name: 'Alpha Officeholder Committee',
  total_amount: '375.00',
  transaction_count: 2,
  identity_is_safe: true
};

function responseWithResult(result: unknown): unknown {
  return {
    query: 'identity',
    by: 'name',
    limit: 20,
    offset: 0,
    rollup_completed_at: '2026-07-17T12:00:00Z',
    results: [result]
  };
}

describe('donor search contract', () => {
  it('pins donor search constants to the backend contract', () => {
    expect(DONOR_SEARCH_MIN_QUERY_LEN).toBe(3);
    expect(DONOR_SEARCH_MAX_LIMIT).toBe(50);
    expect(DONOR_SEARCH_BY_MODES).toEqual(['name', 'employer', 'zip']);
  });

  it('builds donor API paths while preserving backend-owned values', () => {
    expect(buildDonorSearchPath({ q: ' Jane ', by: 'name', limit: 20, offset: 0 })).toBe(
      '/v1/donors/search?q=+Jane+&by=name&limit=20&offset=0'
    );
    expect(buildDonorSearchPath({ q: '27701-1234', by: 'zip' })).toBe(
      '/v1/donors/search?q=27701-1234&by=zip'
    );
    expect(buildDonorSearchPath({ q: 'Jane', by: 'bogus' })).toBe(
      '/v1/donors/search?q=Jane&by=bogus'
    );
  });

  it('builds donor page paths without forcing empty query params', () => {
    expect(buildDonorPagePath({ q: '', by: '' })).toBe('/donors');
    expect(buildDonorPagePath({ by: 'employer' })).toBe('/donors?by=employer');
    expect(buildDonorPagePath({ q: 'Jane', by: 'name', limit: 20, offset: 0 })).toBe(
      '/donors?q=Jane&by=name&limit=20&offset=0'
    );
  });

  it('guides only one- or two-character name and employer searches', () => {
    expect(hasDonorShortNameQueryGuidance('J', 'name')).toBe(true);
    expect(hasDonorShortNameQueryGuidance(' Ja ', 'employer')).toBe(true);
    expect(hasDonorShortNameQueryGuidance('', 'name')).toBe(false);
    expect(hasDonorShortNameQueryGuidance('   ', 'name')).toBe(false);
    expect(hasDonorShortNameQueryGuidance('Jan', 'name')).toBe(false);
    expect(hasDonorShortNameQueryGuidance('27', 'zip')).toBe(false);
    expect(hasDonorShortNameQueryGuidance('Ja', 'bogus')).toBe(false);
  });

  it('recognizes only supported donor search modes', () => {
    expect(isDonorSearchByMode('name')).toBe(true);
    expect(isDonorSearchByMode('employer')).toBe(true);
    expect(isDonorSearchByMode('zip')).toBe(true);
    expect(isDonorSearchByMode('committee')).toBe(false);
    expect(isDonorSearchByMode('')).toBe(false);
  });

  it.each([
    ['unresolved fallback', unresolvedResult],
    ['resolved combined identity', resolvedResult],
    ['resolved identity with possible_match candidate', possibleMatchResult]
  ])('accepts the exact %s API fixture', (_label, result) => {
    const payload = responseWithResult(result);

    expect(() => assertDonorSearchResponse(payload)).not.toThrow();
  });

  it('rejects a response that omits the rollup build timestamp contract', () => {
    const payload = responseWithResult(unresolvedResult) as Record<string, unknown>;
    delete payload.rollup_completed_at;

    expect(() => assertDonorSearchResponse(payload)).toThrow(
      'rollup_completed_at must be a string.'
    );
  });

  it('rejects a successful response with a null rollup build timestamp', () => {
    const payload = responseWithResult(unresolvedResult) as Record<string, unknown>;
    payload.rollup_completed_at = null;

    expect(() => assertDonorSearchResponse(payload)).toThrow(
      'rollup_completed_at must be a string.'
    );
  });

  it('rejects a result when a required nullable identity field is omitted', () => {
    const result = structuredClone(unresolvedResult) as Record<string, unknown>;
    delete result.donor_identity_id;

    expect(() => assertDonorSearchResponse(responseWithResult(result))).toThrow(
      'results[0].donor_identity_id must be a string or null.'
    );
  });

  it('rejects a result when a required nullable contributor field is omitted', () => {
    const result = structuredClone(unresolvedResult) as Record<string, unknown>;
    delete result.contributor_employer;

    expect(() => assertDonorSearchResponse(responseWithResult(result))).toThrow(
      'results[0].contributor_employer must be a string or null.'
    );
  });

  it('rejects an underlying record without source evidence', () => {
    const result = structuredClone(resolvedResult);
    result.underlying_records[0].sources = [];

    expect(() => assertDonorSearchResponse(responseWithResult(result))).toThrow(
      'results[0].underlying_records[0].sources must contain at least one source.'
    );
  });

  it('rejects an underlying record source without a filing URL', () => {
    const result = structuredClone(possibleMatchResult);
    const candidateSource = result.not_combined_candidates[0].sources[0] as {
      record_url: string | null;
    };
    candidateSource.record_url = null;

    expect(() => assertDonorSearchResponse(responseWithResult(result))).toThrow(
      'results[0].not_combined_candidates[0].sources[0].record_url must be a non-empty string.'
    );
  });

  it('rejects candidate confidence vocabulary drift', () => {
    const result = structuredClone(possibleMatchResult);
    result.not_combined_candidates[0].confidence_band = 'probable_match';

    expect(() => assertDonorSearchResponse(responseWithResult(result))).toThrow(
      'results[0].not_combined_candidates[0].confidence_band must be "possible_match".'
    );
  });

  it('accepts a recipient identity flag and tolerates its absence for smoke-parity payloads', () => {
    // Absence stays accepted only because fixture-mode smoke payloads
    // (web/tests/smoke, another lane's files) predate the flag; the render
    // treats a missing flag as identity-unsafe rather than formatting it.
    const withFlag = { ...unresolvedResult, recipients: [{ ...recipient, identity_is_safe: false }] };
    const withoutFlag = { ...unresolvedResult, recipients: [{ ...recipient }] };
    delete (withoutFlag.recipients[0] as { identity_is_safe?: boolean }).identity_is_safe;

    expect(() => assertDonorSearchResponse(responseWithResult(withFlag))).not.toThrow();
    expect(() => assertDonorSearchResponse(responseWithResult(withoutFlag))).not.toThrow();
  });

  it('rejects a recipient whose identity flag is not a boolean', () => {
    const result = {
      ...unresolvedResult,
      recipients: [{ ...recipient, identity_is_safe: 'true' }]
    };

    expect(() => assertDonorSearchResponse(responseWithResult(result))).toThrow(
      'results[0].recipients[0].identity_is_safe must be a boolean when present.'
    );
  });
});
