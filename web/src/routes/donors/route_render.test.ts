import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';
import {
  DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME,
  DONOR_LOOKUP_SEED_EMPLOYER,
  DONOR_LOOKUP_SEED_PERSON_ID,
  DONOR_LOOKUP_SEED_TOTAL_AMOUNT,
  DONOR_LOOKUP_SEED_ZIP5
} from '$lib/donors/fixture';
import type { DonorSearchResponse } from '$lib/donors/contract';
import DonorPage from './+page.svelte';

let currentPageUrl = new URL('https://civibus.test/');
type DonorPageRenderData = DonorSearchResponse & {
  shortQueryGuidance?: boolean;
  validationMessage?: string;
};

vi.mock('$app/stores', () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: currentPageUrl });
      return () => {};
    }
  },
  navigating: {
    subscribe(run: (value: null) => void): () => void {
      run(null);
      return () => {};
    }
  }
}));

function donorResponse(overrides: Partial<DonorPageRenderData> = {}): DonorPageRenderData {
  return {
    query: 'Jane',
    by: 'name',
    limit: 20,
    offset: 0,
    results: [
      {
        id: '72000000-0000-0000-0000-000000000101',
        contributor_name: DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME,
        contributor_employer: DONOR_LOOKUP_SEED_EMPLOYER,
        contributor_occupation: 'Engineer',
        contributor_city: 'Durham',
        contributor_state: 'NC',
        normalized_zip5: DONOR_LOOKUP_SEED_ZIP5,
        total_amount: DONOR_LOOKUP_SEED_TOTAL_AMOUNT,
        transaction_count: 3,
        latest_transaction_date: '2024-07-15',
        recipients: [
          {
            person_id: DONOR_LOOKUP_SEED_PERSON_ID,
            candidate_id: '72000000-0000-0000-0000-000000000014',
            fec_candidate_id: 'H0NC01001',
            candidate_name: 'Alpha Officeholder',
            committee_id: '72000000-0000-0000-0000-000000000015',
            fec_committee_id: 'C72000001',
            committee_name: 'Alpha Officeholder Committee',
            total_amount: '375.00',
            transaction_count: 2
          }
        ],
        sources: [
          {
            domain: 'campaign_finance',
            jurisdiction: 'federal/fec',
            data_source_name: 'Campaign Finance API Source donor-search-fixture',
            data_source_url: 'https://example.org/campaign-finance-source',
            source_record_key: 'donor-search-current',
            record_url: 'https://example.org/fec/donor-search/current',
            pull_date: '2026-07-09T12:00:00Z'
          }
        ]
      }
    ],
    ...overrides
  };
}

describe('/donors route rendering', () => {
  beforeEach(() => {
    currentPageUrl = new URL('https://preview.internal:5173/donors?q=Jane&by=name');
  });

  it('renders populated donor rows with money, recipient links, and seed fields', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse()
      }
    });

    expect(rendered.body).toContain(DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME);
    expect(rendered.body).toContain(DONOR_LOOKUP_SEED_EMPLOYER);
    expect(rendered.body).toContain(DONOR_LOOKUP_SEED_ZIP5);
    expect(rendered.body).toContain('$500.00');
    expect(rendered.body).toContain('data-testid="donor-result-count"');
    expect(rendered.body).toContain('Showing donors 1-1.');
    expect(rendered.body).toContain(`href="/person/${DONOR_LOOKUP_SEED_PERSON_ID}"`);
    expect(rendered.body).toContain('href="https://example.org/campaign-finance-source"');
    expect(rendered.body).toContain('href="https://example.org/fec/donor-search/current"');
    expect(rendered.body).toContain('data-testid="donor-result-row"');
  });

  it('renders zero-results copy without a table', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({ results: [] })
      }
    });

    expect(rendered.body).toContain('No donors match this search.');
    expect(rendered.body).not.toContain('<table');
  });

  it('renders short-query guidance without a table', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({
          query: 'Ja',
          results: [],
          shortQueryGuidance: true
        })
      }
    });

    expect(rendered.body).toContain('Enter at least 3 characters to search by name or employer.');
    expect(rendered.body).not.toContain('<table');
  });

  it('renders the pinned scope-honesty caveat', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({ results: [] })
      }
    });

    expect(rendered.body).toContain('data-testid="donor-scope-note"');
    expect(rendered.body).toContain(
      'Results cover itemized contributions to committees of current federal officeholders only. Unitemized (&lt;$200) contributions are not included.'
    );
  });
});
