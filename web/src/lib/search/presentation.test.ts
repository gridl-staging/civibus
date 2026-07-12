import { describe, expect, it } from 'vitest';
import { SEARCH_QUERY_MIN_LENGTH } from './contract';
import {
  buildSearchResultKey,
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
        'Search people, organizations, committees, candidates, offices, and contests across campaign-finance and civic records.'
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
        href: '/person/11111111-1111-4111-8111-111111111111',
        contextLine: ''
      },
      {
        name: 'Org Two',
        entityType: 'org',
        entityId: '22222222-2222-4222-8222-222222222222',
        routeLabel: 'Organization',
        href: '/org/22222222-2222-4222-8222-222222222222',
        contextLine: ''
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
        href: '/office/55555555-5555-4555-8555-555555555555',
        contextLine: ''
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
        href: '/person/66666666-6666-4666-8666-666666666666',
        contextLine: ''
      }
    ]);
  });

  it('builds a contest result card that routes to the contest detail page', () => {
    const results = [
      {
        entity_type: 'contest',
        entity_id: '77777777-7777-4777-8777-777777777777',
        name: 'General Election Contest'
      }
    ] as any;

    expect(buildSearchResultCards(results)).toEqual([
      {
        name: 'General Election Contest',
        entityType: 'contest',
        entityId: '77777777-7777-4777-8777-777777777777',
        routeLabel: 'Contest',
        href: '/contest/77777777-7777-4777-8777-777777777777',
        contextLine: ''
      }
    ]);
  });

  it('builds distinct render keys when multiple result types share the same UUID', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'person',
        entity_id: '99999999-9999-4999-8999-999999999999',
        name: 'Jane Doe'
      },
      {
        entity_type: 'candidate',
        entity_id: '99999999-9999-4999-8999-999999999999',
        name: 'Jane Doe'
      }
    ] as any);

    expect(cards.map(buildSearchResultKey)).toEqual([
      'person:99999999-9999-4999-8999-999999999999',
      'candidate:99999999-9999-4999-8999-999999999999'
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
      `Search supports people, organizations, committees, candidates, offices, and contests. Enter at least ${SEARCH_QUERY_MIN_LENGTH} characters.`
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
        },
        {
          entity_type: 'contest',
          entity_id: '77777777-7777-4777-8777-777777777777',
          name: 'General Election Contest'
        }
      ])
    ).toEqual([
      {
        entityType: 'person',
        entityId: '11111111-1111-4111-8111-111111111111',
        name: 'Person One',
        routeLabel: 'Person',
        href: '/person/11111111-1111-4111-8111-111111111111',
        contextLine: ''
      },
      {
        entityType: 'org',
        entityId: '22222222-2222-4222-8222-222222222222',
        name: 'Org Two',
        routeLabel: 'Organization',
        href: '/org/22222222-2222-4222-8222-222222222222',
        contextLine: ''
      },
      {
        entityType: 'committee',
        entityId: '33333333-3333-4333-8333-333333333333',
        name: 'Committee Three',
        routeLabel: 'Committee',
        href: '/committee/33333333-3333-4333-8333-333333333333',
        contextLine: ''
      },
      {
        entityType: 'candidate',
        entityId: '55555555-5555-4555-8555-555555555555',
        name: 'Candidate Four',
        routeLabel: 'Candidate',
        href: '/person/55555555-5555-4555-8555-555555555555',
        contextLine: ''
      },
      {
        entityType: 'office',
        entityId: '44444444-4444-4444-8444-444444444444',
        name: 'Governor',
        routeLabel: 'Office',
        href: '/office/44444444-4444-4444-8444-444444444444',
        contextLine: ''
      },
      {
        entityType: 'contest',
        entityId: '77777777-7777-4777-8777-777777777777',
        name: 'General Election Contest',
        routeLabel: 'Contest',
        href: '/contest/77777777-7777-4777-8777-777777777777',
        contextLine: ''
      }
    ]);
  });

  it('reconciles failed action form state ahead of URL data for displayed query, filter, and validation copy', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: 'civ',
      entityType: 'org',
      results: [
        {
          entity_type: 'org',
          entity_id: '22222222-2222-4222-8222-222222222222',
          name: 'Civibus Org'
        }
      ],
      form: {
        query: 'c',
        entityType: 'candidate',
        validationMessage: 'query.q: String should have at least 2 characters'
      }
    });

    expect(pagePresentation.queryValue).toBe('c');
    expect(pagePresentation.selectedEntityType).toBe('candidate');
    expect(pagePresentation.inlineValidationMessage).toBe(
      'query.q: String should have at least 2 characters'
    );
    expect(pagePresentation.submitButtonLabel).toBe('Search');
    expect(pagePresentation.statusMessage).toBe('Search could not run. Fix validation issues and try again.');
    expect(pagePresentation.resultCards).toEqual([]);
  });

  it('falls back to page data validationMessage when form is null', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: 'c',
      entityType: 'candidate',
      results: [],
      validationMessage: 'query.q: String should have at least 2 characters'
    } as any);

    expect(pagePresentation.inlineValidationMessage).toBe(
      'query.q: String should have at least 2 characters'
    );
    expect(pagePresentation.statusMessage).toBe('Search could not run. Fix validation issues and try again.');
  });

  it('derives deterministic pending labels when a submit is in progress', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: 'civ',
      entityType: 'org',
      results: [],
      isSubmitting: true
    });

    expect(pagePresentation.submitButtonLabel).toBe('Searching...');
    expect(pagePresentation.statusMessage).toBe('Searching...');
  });

  it('builds rich context lines for disambiguating metadata', () => {
    const results: SearchResultCardData[] = [
      {
        entity_type: 'candidate',
        entity_id: '88888888-8888-4888-8888-888888888888',
        name: 'Pat Candidate',
        office_name: 'Governor',
        party: 'DEM',
        state: 'OR'
      },
      {
        entity_type: 'committee',
        entity_id: '99999999-9999-4999-8999-999999999999',
        name: 'Citizens for Progress',
        committee_type: 'super_pac',
        party: 'IND',
        state: 'CA',
        total_raised: 250000
      }
    ];

    expect(buildSearchResultCards(results)).toEqual([
      {
        entityType: 'candidate',
        entityId: '88888888-8888-4888-8888-888888888888',
        name: 'Pat Candidate',
        routeLabel: 'Candidate',
        href: '/person/88888888-8888-4888-8888-888888888888',
        contextLine: 'Democrat · Governor · OR'
      },
      {
        entityType: 'committee',
        entityId: '99999999-9999-4999-8999-999999999999',
        name: 'Citizens for Progress',
        routeLabel: 'Committee',
        href: '/committee/99999999-9999-4999-8999-999999999999',
        contextLine: 'Independent · Super PAC · $250,000 · CA'
      }
    ]);
  });

  it('builds officeholder person context while keeping generic candidate and committee context', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'person',
        entity_id: '16161616-1616-4161-8161-161616161616',
        name: 'House Officeholder',
        office_name: 'U.S. Representative',
        state: 'LA-04',
        party: 'REP'
      },
      {
        entity_type: 'person',
        entity_id: '17171717-1717-4171-8171-171717171717',
        name: 'Bare Person',
        office_name: null,
        state: null,
        party: null
      },
      {
        entity_type: 'candidate',
        entity_id: '18181818-1818-4181-8181-181818181818',
        name: 'Candidate Result',
        office_name: 'Governor',
        state: 'OR',
        party: 'DEM'
      },
      {
        entity_type: 'committee',
        entity_id: '19191919-1919-4191-8191-191919191919',
        name: 'Committee Result',
        committee_type: 'pac',
        state: 'CA',
        party: 'DEM'
      }
    ]);

    expect(cards.map((card) => card.contextLine)).toEqual([
      'U.S. Representative · LA-04 · Republican',
      '',
      'Democrat · Governor · OR',
      'Democrat · PAC · CA'
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
      { label: 'Office', href: '/search?entity_type=office' },
      { label: 'Contest', href: '/search?entity_type=contest' }
    ]);
  });

  // --- Loading skeleton contract (Stage 1 red-phase tests) ---

  it('returns showResultsSkeleton true when isSubmitting is true', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: 'civ',
      entityType: '',
      results: [],
      isSubmitting: true
    });

    expect((pagePresentation as Record<string, unknown>).showResultsSkeleton).toBe(true);
  });

  it('returns showResultsSkeleton false for all non-submitting states', () => {
    const emptyQuery = buildSearchPagePresentation({
      query: '',
      entityType: '',
      results: []
    });
    expect((emptyQuery as Record<string, unknown>).showResultsSkeleton).toBe(false);

    const withResults = buildSearchPagePresentation({
      query: 'civ',
      entityType: '',
      results: [
        {
          entity_type: 'person',
          entity_id: '11111111-1111-4111-8111-111111111111',
          name: 'Person One'
        }
      ]
    });
    expect((withResults as Record<string, unknown>).showResultsSkeleton).toBe(false);

    const zeroResults = buildSearchPagePresentation({
      query: 'zzzzz',
      entityType: '',
      results: []
    });
    expect((zeroResults as Record<string, unknown>).showResultsSkeleton).toBe(false);

    const validationError = buildSearchPagePresentation({
      query: 'c',
      entityType: '',
      results: [],
      form: {
        query: 'c',
        entityType: '',
        validationMessage: 'query.q: String should have at least 2 characters'
      }
    });
    expect((validationError as Record<string, unknown>).showResultsSkeleton).toBe(false);
  });

  it('suppresses stale resultCards when isSubmitting is true', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: 'civ',
      entityType: '',
      results: [
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
      ],
      isSubmitting: true
    });

    expect(pagePresentation.resultCards).toEqual([]);
  });

  it('keeps statusMessage as Searching when isSubmitting is true even with stale results', () => {
    const pagePresentation = buildSearchPagePresentation({
      query: 'civ',
      entityType: '',
      results: [
        {
          entity_type: 'person',
          entity_id: '11111111-1111-4111-8111-111111111111',
          name: 'Person One'
        }
      ],
      isSubmitting: true
    });

    expect(pagePresentation.statusMessage).toBe('Searching...');
  });

  // --- Five-state regression matrix (Stage 3) ---

  describe('five-state presentation matrix', () => {
    it('empty state: statusMessage prompts for input, showResultsSkeleton false, resultCards empty', () => {
      const vm = buildSearchPagePresentation({
        query: '',
        entityType: '',
        results: []
      });

      expect(vm.statusMessage).toBe(
        `Enter at least ${SEARCH_QUERY_MIN_LENGTH} characters to search.`
      );
      expect(vm.showResultsSkeleton).toBe(false);
      expect(vm.resultCards).toEqual([]);
      expect(vm.guidanceBlock).toContain('Search supports');
      expect(vm.submitButtonLabel).toBe('Search');
    });

    it('results state: statusMessage reports count, showResultsSkeleton false, resultCards populated', () => {
      const vm = buildSearchPagePresentation({
        query: 'jane',
        entityType: '',
        results: [
          {
            entity_type: 'person',
            entity_id: '11111111-1111-4111-8111-111111111111',
            name: 'Jane Smith'
          },
          {
            entity_type: 'org',
            entity_id: '22222222-2222-4222-8222-222222222222',
            name: 'Jane Corp'
          }
        ]
      });

      expect(vm.statusMessage).toBe('2 results found.');
      expect(vm.showResultsSkeleton).toBe(false);
      expect(vm.resultCards).toHaveLength(2);
      expect(vm.resultCards[0].name).toBe('Jane Smith');
      expect(vm.resultCards[1].name).toBe('Jane Corp');
      expect(vm.guidanceBlock).toBe('');
      expect(vm.submitButtonLabel).toBe('Search');
    });

    it('zero-results state: statusMessage says no records, showResultsSkeleton false, resultCards empty', () => {
      const vm = buildSearchPagePresentation({
        query: 'xyznonexistent',
        entityType: 'person',
        results: []
      });

      expect(vm.statusMessage).toBe('No matching records found.');
      expect(vm.showResultsSkeleton).toBe(false);
      expect(vm.resultCards).toEqual([]);
      expect(vm.guidanceBlock).toBe('');
      expect(vm.submitButtonLabel).toBe('Search');
      expect(vm.selectedEntityType).toBe('person');
    });

    it('validation-error state: statusMessage shows validation failure, showResultsSkeleton false, resultCards empty even with stale URL results', () => {
      const vm = buildSearchPagePresentation({
        query: 'civ',
        entityType: 'org',
        results: [
          {
            entity_type: 'org',
            entity_id: '22222222-2222-4222-8222-222222222222',
            name: 'Civibus Org'
          }
        ],
        form: {
          query: 'c',
          entityType: 'candidate',
          validationMessage: 'query.q: String should have at least 2 characters'
        }
      });

      expect(vm.statusMessage).toBe('Search could not run. Fix validation issues and try again.');
      expect(vm.showResultsSkeleton).toBe(false);
      expect(vm.resultCards).toEqual([]);
      expect(vm.queryValue).toBe('c');
      expect(vm.selectedEntityType).toBe('candidate');
      expect(vm.inlineValidationMessage).toBe('query.q: String should have at least 2 characters');
      expect(vm.submitButtonLabel).toBe('Search');
    });

    it('pending state: preserves submitted query/filter while forcing skeleton and clearing stale results', () => {
      const vm = buildSearchPagePresentation({
        query: 'jane',
        entityType: 'person',
        results: [
          {
            entity_type: 'person',
            entity_id: '11111111-1111-4111-8111-111111111111',
            name: 'Jane Smith'
          }
        ],
        isSubmitting: true
      });

      expect(vm.queryValue).toBe('jane');
      expect(vm.selectedEntityType).toBe('person');
      expect(vm.submitButtonLabel).toBe('Searching...');
      expect(vm.statusMessage).toBe('Searching...');
      expect(vm.showResultsSkeleton).toBe(true);
      expect(vm.resultCards).toEqual([]);
    });
  });
});
