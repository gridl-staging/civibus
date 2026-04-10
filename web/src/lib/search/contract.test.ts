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
      }
    ];

    expect(results.map((result) => toSearchResultHref(result))).toEqual([
      '/person/11111111-1111-4111-8111-111111111111',
      '/org/22222222-2222-4222-8222-222222222222',
      '/committee/33333333-3333-4333-8333-333333333333',
      '/person/44444444-4444-4444-8444-444444444444'
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

  it('includes candidate in the supported entity types array', () => {
    expect(SEARCH_ENTITY_TYPES).toEqual(['person', 'org', 'committee', 'candidate', 'office']);
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
      }
    ]);
  });

  it('keeps candidate in the UI filter list while still allowing backend-owned passthrough values', () => {
    expect(SEARCH_ENTITY_TYPES).toContain('candidate');
    expect(buildSearchPath({ q: 'civ', entityType: 'candidate' })).toBe('/v1/search?q=civ&entity_type=candidate');
  });
});
