import { describe, expect, it } from 'vitest';
import {
  buildSearchPagePath,
  buildSearchPath,
  filterRenderableSearchResults,
  isSearchEntityType,
  isRenderableSearchResult,
  SEARCH_ENTITY_TYPES,
  SEARCH_QUERY_MIN_LENGTH,
  toSearchResultHref,
  type SearchApiResult,
  type SearchApiResultPayload
} from './contract';

describe('search contract', () => {
  it('pins the backend query minimum length to two characters', () => {
    expect(SEARCH_QUERY_MIN_LENGTH).toBe(2);
  });


  it('maps UUID search results to UUID route hrefs', () => {
    const results: SearchApiResult[] = [
      {
        entity_type: 'person',
        entity_id: '11111111-1111-4111-8111-111111111111',
        name: 'Person One'
      },
      {
        entity_type: 'org',
        entity_id: '22222222-2222-4222-8222-222222222222',
        name: 'Org Two'
      },
      {
        entity_type: 'committee',
        entity_id: '33333333-3333-4333-8333-333333333333',
        name: 'Committee Three'
      },
      {
        entity_type: 'candidate',
        entity_id: '44444444-4444-4444-8444-444444444444',
        name: 'Candidate Four'
      },
      {
        entity_type: 'contest',
        entity_id: '55555555-5555-4555-8555-555555555555',
        name: 'Contest Five'
      }
    ];

    expect(results.map((result) => toSearchResultHref(result))).toEqual([
      '/person/11111111-1111-4111-8111-111111111111',
      '/org/22222222-2222-4222-8222-222222222222',
      '/committee/33333333-3333-4333-8333-333333333333',
      '/person/44444444-4444-4444-8444-444444444444',
      '/contest/55555555-5555-4555-8555-555555555555'
    ]);
  });

  it('rejects non-UUID identifiers in route mapping', () => {
    expect(() =>
      toSearchResultHref({
        entity_type: 'person',
        entity_id: 'alice-smith'
      })
    ).toThrow(/uuid/i);
  });

  it('preserves backend-owned query values instead of trimming them in the frontend', () => {
    expect(buildSearchPath({ q: ' civ ' })).toBe('/v1/search?q=+civ+');
  });

  it('omits only the form empty-string sentinel for the all-types filter', () => {
    expect(buildSearchPath({ q: 'civ', entityType: '' })).toBe('/v1/search?q=civ');
    expect(buildSearchPath({ q: 'civ', entityType: ' ' })).toBe('/v1/search?q=civ&entity_type=+');
  });

  it('builds /search page paths without forcing an empty q param', () => {
    expect(buildSearchPagePath({ entityType: 'person' })).toBe('/search?entity_type=person');
    expect(buildSearchPagePath({ q: 'civ', entityType: 'office' })).toBe(
      '/search?q=civ&entity_type=office'
    );
    expect(buildSearchPagePath({ q: '', entityType: '' })).toBe('/search');
  });

  // --- Office search integration contract (Stage 1 red-phase tests) ---

  it('includes candidate, office, and contest in the supported entity types array', () => {
    expect(SEARCH_ENTITY_TYPES).toEqual([
      'person',
      'org',
      'committee',
      'candidate',
      'office',
      'contest'
    ]);
  });

  it('maps office search results to /office/<uuid> route hrefs', () => {
    const result = toSearchResultHref({
      entity_type: 'office' as any,
      entity_id: '44444444-4444-4444-8444-444444444444'
    });
    expect(result).toBe('/office/44444444-4444-4444-8444-444444444444');
  });

  it('recognizes office as a valid search entity type', () => {
    expect(isSearchEntityType('office')).toBe(true);
  });

  it('recognizes candidate as a valid search entity type', () => {
    expect(isSearchEntityType('candidate')).toBe(true);
  });

  it('recognizes contest as a valid search entity type', () => {
    expect(isSearchEntityType('contest')).toBe(true);
  });

  it('accepts only supported entity types with UUID ids as renderable search results', () => {
    expect(
      isRenderableSearchResult({
        entity_type: 'candidate',
        entity_id: '55555555-5555-4555-8555-555555555555',
        name: 'Pat Candidate'
      })
    ).toBe(true);
    expect(
      isRenderableSearchResult({
        entity_type: 'office',
        entity_id: '44444444-4444-4444-8444-444444444444',
        name: 'Governor'
      })
    ).toBe(true);
    expect(
      isRenderableSearchResult({
        entity_type: 'contest',
        entity_id: '66666666-6666-4666-8666-666666666666',
        name: 'General Election Contest'
      })
    ).toBe(true);
    expect(
      isRenderableSearchResult({
        entity_type: 'person',
        entity_id: 'not-a-uuid',
        name: 'Alice'
      })
    ).toBe(false);
  });

  it('filters backend search payloads down to renderable frontend routes', () => {
    const payloads: SearchApiResultPayload[] = [
      {
        entity_type: 'candidate',
        entity_id: '55555555-5555-4555-8555-555555555555',
        name: 'Pat Candidate'
      },
      {
        entity_type: 'office',
        entity_id: '44444444-4444-4444-8444-444444444444',
        name: 'Governor'
      },
      {
        entity_type: 'contest',
        entity_id: '66666666-6666-4666-8666-666666666666',
        name: 'General Election Contest'
      },
      {
        entity_type: 'person',
        entity_id: 'not-a-uuid',
        name: 'Alice'
      }
    ];

    expect(filterRenderableSearchResults(payloads)).toEqual([
      {
        entity_type: 'candidate',
        entity_id: '55555555-5555-4555-8555-555555555555',
        name: 'Pat Candidate'
      },
      {
        entity_type: 'office',
        entity_id: '44444444-4444-4444-8444-444444444444',
        name: 'Governor'
      },
      {
        entity_type: 'contest',
        entity_id: '66666666-6666-4666-8666-666666666666',
        name: 'General Election Contest'
      }
    ]);
  });

  it('keeps candidate in the UI filter list while still allowing backend-owned passthrough values', () => {
    expect(SEARCH_ENTITY_TYPES).toContain('candidate');
    expect(buildSearchPath({ q: 'civ', entityType: 'candidate' })).toBe('/v1/search?q=civ&entity_type=candidate');
  });

  // --- Context field passthrough (Stage 4 pin tests) ---

  it('passes through optional context fields on renderable results unchanged', () => {
    const payload: SearchApiResultPayload = {
      entity_type: 'committee',
      entity_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      name: 'Citizens for Progress',
      state: 'CA',
      party: 'DEM',
      office_name: null,
      committee_type: 'pac',
      total_raised: 250000
    };

    expect(isRenderableSearchResult(payload)).toBe(true);
    const filtered = filterRenderableSearchResults([payload]);
    expect(filtered).toHaveLength(1);
    expect(filtered[0].state).toBe('CA');
    expect(filtered[0].party).toBe('DEM');
    expect(filtered[0].office_name).toBeNull();
    expect(filtered[0].committee_type).toBe('pac');
    expect(filtered[0].total_raised).toBe(250000);
  });

  it('passes through serialized decimal total_raised strings unchanged', () => {
    const payload: SearchApiResultPayload = {
      entity_type: 'committee',
      entity_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      name: 'Serialized Money Committee',
      total_raised: '150000.00'
    };

    expect(isRenderableSearchResult(payload)).toBe(true);
    const filtered = filterRenderableSearchResults([payload]);
    expect(filtered).toHaveLength(1);
    expect(filtered[0].total_raised).toBe('150000.00');
  });

  it('validates results with no context fields as renderable', () => {
    const payload: SearchApiResultPayload = {
      entity_type: 'person',
      entity_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      name: 'Alice Smith'
    };

    expect(isRenderableSearchResult(payload)).toBe(true);
    const filtered = filterRenderableSearchResults([payload]);
    expect(filtered).toHaveLength(1);
    expect(filtered[0].state).toBeUndefined();
    expect(filtered[0].party).toBeUndefined();
  });
});
