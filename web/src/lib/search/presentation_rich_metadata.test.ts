import { describe, expect, it } from 'vitest';
import { buildSearchPagePresentation, buildSearchResultCards } from './presentation';

describe('search presentation rich metadata', () => {
  it('builds committee card metadata combining party, committee type, and state', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'committee',
        entity_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        name: 'Citizens for Progress',
        state: 'CA',
        party: 'DEM',
        committee_type: 'pac'
      }
    ]);

    expect(cards[0].contextLine).toBe('Democrat · PAC · CA');
  });

  it('builds candidate card metadata combining party, office, and state', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'candidate',
        entity_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        name: 'Pat Candidate',
        party: 'REP',
        office_name: 'U.S. Senate',
        state: 'TX'
      }
    ]);

    expect(cards[0].contextLine).toBe('Republican · U.S. Senate · TX');
  });

  it('builds officeholder person metadata for senate delegate and executive offices', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'person',
        entity_id: '16161616-1616-4161-8161-161616161616',
        name: 'Senate Officeholder',
        party: 'REP',
        office_name: 'U.S. Senator',
        state: 'CA'
      },
      {
        entity_type: 'person',
        entity_id: '17171717-1717-4171-8171-171717171717',
        name: 'Delegate Officeholder',
        party: 'IND',
        office_name: 'U.S. Delegate',
        state: 'DC-AL'
      },
      {
        entity_type: 'person',
        entity_id: '18181818-1818-4181-8181-181818181818',
        name: 'Executive Officeholder',
        party: 'DEM',
        office_name: 'President of the United States',
        state: null
      }
    ]);

    expect(cards.map((card) => card.contextLine)).toEqual([
      'U.S. Senator · CA · Republican',
      'U.S. Delegate · DC-AL · Independent',
      'President of the United States · Democrat'
    ]);
  });

  it('builds empty metadata when a person result has no context fields', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'person',
        entity_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        name: 'Alice Smith',
        state: null,
        party: null,
        office_name: null,
        committee_type: null,
        total_raised: null
      }
    ]);

    expect(cards[0].contextLine).toBe('');
  });

  it('builds contest metadata from office and state when party is absent', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'contest',
        entity_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
        name: 'Governor General Election',
        office_name: 'Governor',
        state: 'WA'
      }
    ]);

    expect(cards[0].contextLine).toBe('Governor · WA');
  });

  it('builds committee metadata with formatted currency for total_raised and state', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'committee',
        entity_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
        name: 'Example PAC',
        total_raised: 150000,
        state: 'NY'
      }
    ]);

    expect(cards[0].contextLine).toBe('$150,000 · NY');
  });

  it('builds committee metadata with formatted currency when total_raised is a serialized decimal string', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'committee',
        entity_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
        name: 'Serialized Money PAC',
        total_raised: '150000.00',
        state: 'NY'
      }
    ]);

    expect(cards[0].contextLine).toBe('$150,000 · NY');
  });

  it('builds committee metadata with formatted zero currency when total_raised is zero', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'committee',
        entity_id: '12121212-1212-4121-8121-121212121212',
        name: 'Zero Balance Committee',
        total_raised: '0.00',
        state: 'AZ'
      }
    ]);

    expect(cards[0].contextLine).toBe('$0 · AZ');
  });

  it('builds committee metadata with formatted negative currency when total_raised is negative', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'committee',
        entity_id: '13131313-1313-4131-8131-131313131313',
        name: 'Debt Committee',
        total_raised: '-5000',
        state: 'NY'
      }
    ]);

    expect(cards[0].contextLine).toBe('-$5,000 · NY');
  });

  it('keeps unknown party labels unchanged in context metadata', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'candidate',
        entity_id: '14141414-1414-4141-8141-141414141414',
        name: 'Taylor Example',
        party: 'WFP',
        office_name: 'Comptroller',
        state: 'NY'
      }
    ]);

    expect(cards[0].contextLine).toBe('WFP · Comptroller · NY');
  });

  it('keeps unknown committee type labels unchanged in context metadata', () => {
    const cards = buildSearchResultCards([
      {
        entity_type: 'committee',
        entity_id: '15151515-1515-4151-8151-151515151515',
        name: 'Civic Action Committee',
        party: 'DEM',
        committee_type: 'joint_fundraising',
        state: 'CA'
      }
    ]);

    expect(cards[0].contextLine).toBe('Democrat · joint_fundraising · CA');
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
      { value: 'office', label: 'Office' },
      { value: 'contest', label: 'Contest' }
    ]);
    expect(pagePresentation.queryPlaceholder).toBe(
      'Search people, organizations, committees, candidates, offices, or contests'
    );
  });
});
