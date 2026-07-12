import { describe, expect, it } from 'vitest';
import {
  buildDonorPagePath,
  buildDonorSearchPath,
  DONOR_SEARCH_BY_MODES,
  DONOR_SEARCH_MAX_LIMIT,
  DONOR_SEARCH_MIN_QUERY_LEN,
  hasDonorShortNameQueryGuidance,
  isDonorSearchByMode
} from './contract';

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
});
