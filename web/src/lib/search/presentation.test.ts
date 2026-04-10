import { describe, expect, it } from 'vitest';
import { SEARCH_QUERY_MIN_LENGTH } from './contract';
import {
  buildSearchPagePresentation,
  buildSearchMetadata,
  buildSearchResultCards,
  getSearchStatusMessage,
  type SearchResultCardData
} from './presentation';

describe('search presentation', () => {
  it('shows baseline guidance on empty form state', () => {
    expect(getSearchStatusMessage({ query: '', resultCount: 0 })).toBe(
      `Enter at least ${SEARCH_QUERY_MIN_LENGTH} characters to search.`
    );
  });

  it('shows no-results state for submitted queries with empty results', () => {
    expect(getSearchStatusMessage({ query: 'civ', resultCount: 0 })).toBe(
      'No matching records found.'
    );
  });

  it('treats whitespace-only queries as submitted state once the backend has seen them', () => {
    expect(getSearchStatusMessage({ query: '  ', resultCount: 0 })).toBe('No matching records found.');
  });

  it('builds default route metadata for blank search state', () => {
    expect(buildSearchMetadata({ query: '', resultCount: 0 })).toEqual({
      title: 'Search | Civibus',
      description:
        'Search people, organizations, committees, candidates, and offices across campaign-finance and civic records.'
    });
  });

  it('builds query-specific route metadata from current results', () => {
    expect(buildSearchMetadata({ query: 'civ', resultCount: 2 })).toEqual({
      title: 'civ (2 results) | Search | Civibus',
      description: '2 results for "civ" across Civibus records.'
    });
  });

  it('trims surrounding query whitespace before building route metadata strings', () => {
    expect(buildSearchMetadata({ query: '  civ  ', resultCount: 1 })).toEqual({
      title: 'civ (1 result) | Search | Civibus',
      description: '1 result for "civ" across Civibus records.'
    });
  });

  it('builds result cards with hrefs from the shared UUID mapper', () => {
    const results: SearchResultCardData[] = [
      {
        entity_type: 'person',
        entity_id: '11111111-1111-4111-8111-111111111111',
        name: 'Person One'
      },
      {
        entity_type: 'org',
        entity_id: '22222222-2222-4222-8222-222222222222',
        name: 'Org Two'
      }
    ];

    expect(buildSearchResultCards(results)).toEqual([
      {
        name: 'Person One',
        entityType: 'person',
        entityId: '11111111-1111-4111-8111-111111111111',
        routeLabel: 'Person',
        href: '/person/11111111-1111-4111-8111-111111111111'
      },
      {
        name: 'Org Two',
        entityType: 'org',
        entityId: '22222222-2222-4222-8222-222222222222',
        routeLabel: 'Organization',
        href: '/org/22222222-2222-4222-8222-222222222222'
      }
    ]);
  });

  // --- Office search integration contract (Stage 1 red-phase tests) ---

  it('builds an office result card with the correct /office route href', () => {
    const results = [
      {
        entity_type: 'office',
        entity_id: '55555555-5555-4555-8555-555555555555',
        name: 'Governor'
      }
    ] as any;

    expect(buildSearchResultCards(results)).toEqual([
      {
        name: 'Governor',
        entityType: 'office',
        entityId: '55555555-5555-4555-8555-555555555555',
        routeLabel: 'Office',
        href: '/office/55555555-5555-4555-8555-555555555555'
      }
    ]);
  });

  it('builds a candidate result card that routes to the linked person record', () => {
    const results = [
      {
        entity_type: 'candidate',
        entity_id: '66666666-6666-4666-8666-666666666666',
        name: 'Pat Candidate'
      }
    ] as any;

    expect(buildSearchResultCards(results)).toEqual([
      {
        name: 'Pat Candidate',
        entityType: 'candidate',
        entityId: '66666666-6666-4666-8666-666666666666',
        routeLabel: 'Candidate',
        href: '/person/66666666-6666-4666-8666-666666666666'
      }
    ]);
  });

  it('builds a guidance block that explains capabilities and minimum query length', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: '',
      entityType: '',
      results: []
    });
    const contract = pagePresentation as unknown as Record<string, unknown>;

    expect(contract.guidanceBlock).toBe(
      `Search supports people, organizations, committees, candidates, and offices. Enter at least ${SEARCH_QUERY_MIN_LENGTH} characters.`
    );
  });

  it('leaves guidance block empty after a submitted query', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: 'civ',
      entityType: '',
      results: []
    });
    const contract = pagePresentation as unknown as Record<string, unknown>;

    expect(contract.guidanceBlock).toBe('');
  });

  it('builds route labels for result cards separate from raw entity type keys', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'person',
        entity_id: '11111111-1111-4111-8111-111111111111',
        name: 'Person One'
      }
    ]);
    const firstCard = cards[0] as unknown as Record<string, unknown>;

    expect(firstCard.routeLabel).toBe('Person');
  });

  it('builds route labels for all searchable entity types', () => {
    expect(
      buildSearchResultCards([
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
          entity_id: '55555555-5555-4555-8555-555555555555',
          name: 'Candidate Four'
        },
        {
          entity_type: 'office',
          entity_id: '44444444-4444-4444-8444-444444444444',
          name: 'Governor'
        }
      ])
    ).toEqual([
      {
        entityType: 'person',
        entityId: '11111111-1111-4111-8111-111111111111',
        name: 'Person One',
        routeLabel: 'Person',
        href: '/person/11111111-1111-4111-8111-111111111111'
      },
      {
        entityType: 'org',
        entityId: '22222222-2222-4222-8222-222222222222',
        name: 'Org Two',
        routeLabel: 'Organization',
        href: '/org/22222222-2222-4222-8222-222222222222'
      },
      {
        entityType: 'committee',
        entityId: '33333333-3333-4333-8333-333333333333',
        name: 'Committee Three',
        routeLabel: 'Committee',
        href: '/committee/33333333-3333-4333-8333-333333333333'
      },
      {
        entityType: 'candidate',
        entityId: '55555555-5555-4555-8555-555555555555',
        name: 'Candidate Four',
        routeLabel: 'Candidate',
        href: '/person/55555555-5555-4555-8555-555555555555'
      },
      {
        entityType: 'office',
        entityId: '44444444-4444-4444-8444-444444444444',
        name: 'Governor',
        routeLabel: 'Office',
        href: '/office/44444444-4444-4444-8444-444444444444'
      }
    ]);
  });

  it('builds browse links with page routes, filter params, and human-readable labels', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: '',
      entityType: '',
      results: []
    });
    const contract = pagePresentation as unknown as Record<string, unknown>;

    expect(contract.browseLinks).toEqual([
      { label: 'Person', href: '/search?entity_type=person' },
      { label: 'Organization', href: '/search?entity_type=org' },
      { label: 'Committee', href: '/search?entity_type=committee' },
      { label: 'Candidate', href: '/search?entity_type=candidate' },
      { label: 'Office', href: '/search?entity_type=office' }
    ]);
  });

  it('builds select options from the shared presentation contract with candidate included', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: '',
      entityType: 'candidate',
      results: []
    }) as unknown as Record<string, unknown>;

    expect(pagePresentation.selectedEntityType).toBe('candidate');
    expect(pagePresentation.entityTypeOptions).toEqual([
      { value: 'person', label: 'Person' },
      { value: 'org', label: 'Organization' },
      { value: 'committee', label: 'Committee' },
      { value: 'candidate', label: 'Candidate' },
      { value: 'office', label: 'Office' }
    ]);
    expect(pagePresentation.queryPlaceholder).toBe(
      'Search people, organizations, committees, candidates, or offices'
    );
  });
});
