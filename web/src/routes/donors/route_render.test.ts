import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'svelte/server';
import {
  DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME,
  DONOR_LOOKUP_SEED_EMPLOYER,
  DONOR_LOOKUP_SEED_PERSON_ID,
  DONOR_LOOKUP_SEED_TOTAL_AMOUNT,
  DONOR_LOOKUP_SEED_ZIP5
} from '$lib/donors/fixture';
import type {
  DonorResolvedConfidenceBand,
  DonorSearchResponse,
  DonorSearchResult,
  DonorSearchUnderlyingRecord
} from '$lib/donors/contract';
import DonorPage from './+page.svelte';

let currentPageUrl = new URL('https://civibus.test/');
type DonorPageRenderData = Omit<DonorSearchResponse, 'rollup_completed_at'> & {
  rollup_completed_at: string | null;
  shortQueryGuidance?: boolean;
  validationMessage?: string;
  rollupUnavailable?: boolean;
};
type SourceFixture = DonorSearchUnderlyingRecord['sources'][number];

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

const aggregateSource: SourceFixture = {
  domain: 'campaign_finance',
  jurisdiction: 'federal/fec',
  data_source_name: 'Campaign Finance API Source donor-search-fixture',
  data_source_url: 'https://example.org/campaign-finance-source',
  source_record_key: 'donor-search-current',
  record_url: 'https://example.org/fec/donor-search/current',
  pull_date: '2026-07-09T12:00:00Z'
};

function sourceFixture(key: string): SourceFixture {
  return {
    ...aggregateSource,
    data_source_name: `FEC filing ${key}`,
    source_record_key: `donor-search-${key}`,
    record_url: `https://example.org/fec/donor-search/${key}`
  };
}

function unresolvedResult(): DonorSearchResult {
  return {
    id: '72000000-0000-0000-0000-000000000101',
    donor_identity_id: null,
    contributor_name: DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME,
    contributor_employer: DONOR_LOOKUP_SEED_EMPLOYER,
    contributor_occupation: 'Engineer',
    contributor_city: 'Durham',
    contributor_state: 'NC',
    normalized_zip5: DONOR_LOOKUP_SEED_ZIP5,
    total_amount: DONOR_LOOKUP_SEED_TOTAL_AMOUNT,
    transaction_count: 3,
    latest_transaction_date: '2024-07-15',
    combined_record_count: 1,
    confidence_band: null,
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
        transaction_count: 2,
        identity_is_safe: true
      }
    ],
    sources: [aggregateSource],
    underlying_records: [],
    not_combined_candidates: []
  };
}

function underlyingRecordFixture(
  key: string,
  overrides: Partial<DonorSearchUnderlyingRecord> = {}
): DonorSearchUnderlyingRecord {
  return {
    donor_identity_id: '72100000-0000-0000-0000-000000000001',
    contributor_name: `JANE SMITH ${key}`,
    contributor_employer: key === 'a' ? 'Civibus Labs' : null,
    contributor_occupation: key === 'a' ? 'Engineer' : null,
    contributor_city: key === 'a' ? 'Durham' : null,
    contributor_state: key === 'a' ? 'NC' : 'VA',
    normalized_zip5: key === 'a' ? '27701' : null,
    sources: [sourceFixture(key)],
    ...overrides
  };
}

function resolvedResult(
  confidenceBand: DonorResolvedConfidenceBand,
  overrides: Partial<DonorSearchResult> = {}
): DonorSearchResult {
  const underlying_records = [underlyingRecordFixture('a'), underlyingRecordFixture('b')];

  return {
    ...unresolvedResult(),
    id: `72000000-0000-0000-0000-00000000020${confidenceBand === 'match' ? '1' : '2'}`,
    donor_identity_id: '72100000-0000-0000-0000-000000000001',
    contributor_name: 'JANE SMITH',
    contributor_employer: 'Civibus Labs',
    contributor_occupation: 'Engineer',
    contributor_city: 'Durham',
    contributor_state: 'NC',
    normalized_zip5: '27701',
    combined_record_count: underlying_records.length,
    confidence_band: confidenceBand,
    underlying_records,
    not_combined_candidates: [],
    ...overrides
  };
}

function notCombinedCandidateFixture(
  key: string,
  overrides: Partial<DonorSearchUnderlyingRecord> = {}
): DonorSearchResult['not_combined_candidates'][number] {
  return {
    ...underlyingRecordFixture(key, {
      donor_identity_id: '72100000-0000-0000-0000-000000000099',
      ...overrides
    }),
    confidence_band: 'possible_match'
  };
}

function donorResponse(overrides: Partial<DonorPageRenderData> = {}): DonorPageRenderData {
  return {
    query: 'Jane',
    by: 'name',
    limit: 20,
    offset: 0,
    rollup_completed_at: '2026-07-17T12:00:00Z',
    results: [unresolvedResult()],
    ...overrides
  };
}

function countOccurrences(value: string, needle: string): number {
  return value.split(needle).length - 1;
}

describe('/donors route rendering', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-18T12:00:00Z'));
    currentPageUrl = new URL('https://preview.internal:5173/donors?q=Jane&by=name');
  });

  it('renders the current rollup build time without claiming live data', () => {
    const rendered = render(DonorPage, { props: { data: donorResponse() } });

    expect(rendered.body).toContain('data-testid="donor-freshness-stamp"');
    expect(rendered.body).toContain('Donor totals built 1 day ago (2026-07-17)');
    expect(rendered.body.toLowerCase()).not.toContain('live data');
    expect(rendered.body.toLowerCase()).not.toContain('real time');
  });

  it('renders rollup unavailability distinctly from zero results and retains the form values', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({
          query: 'Williams',
          by: 'employer',
          limit: 10,
          offset: 20,
          rollup_completed_at: null,
          results: [],
          rollupUnavailable: true
        })
      }
    });

    expect(rendered.body).toContain(
      'Donor search is temporarily unavailable while contribution data is refreshed.'
    );
    expect(rendered.body).toContain('value="Williams"');
    expect(rendered.body).toContain('<option value="employer" selected="">employer</option>');
    expect(rendered.body).not.toContain('No donors match this search.');
    expect(rendered.body).not.toContain('data-testid="donor-result-row"');
    expect(rendered.body).not.toContain('data-testid="donor-freshness-stamp"');
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
    expect(rendered.body).not.toContain('0 records combined');
    expect(rendered.body).not.toContain('data-testid="donor-identity-disclosure"');
  });

  it('renders a resolved match profile with exactly its combined records and filing links', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({ results: [resolvedResult('match')] })
      }
    });

    expect(rendered.body).toContain('2 records combined');
    expect(rendered.body).toContain('match');
    expect(rendered.body).toContain('records appear to describe the same donor');
    expect(rendered.body).toContain("this isn't the same person");
    expect(rendered.body).toContain('Correction submission is not yet available');
    expect(rendered.body).toContain(
      'aria-describedby="donor-identity-evidence-0-combined-correction-reason"'
    );
    expect(rendered.body).toContain(
      'id="donor-identity-evidence-0-combined-correction-reason"'
    );
    expect(rendered.body).toContain('aria-label="JANE SMITH, 2 records combined"');
    expect(countOccurrences(rendered.body, 'data-testid="donor-identity-underlying-record"')).toBe(2);
    expect(countOccurrences(rendered.body, 'data-testid="donor-identity-underlying-filing"')).toBe(2);
    expect(rendered.body).toContain('JANE SMITH a');
    expect(rendered.body).toContain('JANE SMITH b');
    expect(rendered.body).toContain('href="https://example.org/fec/donor-search/a"');
    expect(rendered.body).toContain('href="https://example.org/fec/donor-search/b"');
    expect(rendered.body).toContain('>—<');
    expect(rendered.body).not.toContain('confidence_band');
    expect(rendered.body).not.toContain('donor_identity_id');
    expect(rendered.body).not.toContain('0.95');
  });

  it('renders a probable match profile with the required may-be-multiple-people caveat', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({ results: [resolvedResult('probable_match')] })
      }
    });

    expect(rendered.body).toContain('2 records combined');
    expect(rendered.body).toContain('probable_match');
    expect(rendered.body).toContain('may be two people');
    expect(rendered.body).toContain("this isn't the same person");
    expect(rendered.body).toContain('Correction submission is not yet available');
    expect(countOccurrences(rendered.body, 'data-testid="donor-identity-underlying-record"')).toBe(2);
    expect(countOccurrences(rendered.body, 'data-testid="donor-identity-underlying-filing"')).toBe(2);
  });

  it('renders possible-match candidates outside the combined record list as not combined', () => {
    const candidate = notCombinedCandidateFixture('near-miss', {
      contributor_name: 'JANE SMYTH',
      contributor_employer: 'Civibus Lab',
      contributor_occupation: 'Architect',
      contributor_city: 'Raleigh',
      contributor_state: 'NC',
      normalized_zip5: '27601',
      sources: [sourceFixture('near-miss')]
    });
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({
          results: [resolvedResult('match', { not_combined_candidates: [candidate] })]
        })
      }
    });
    const combinedRecordList = rendered.body.slice(
      rendered.body.indexOf('data-testid="donor-identity-combined-records"'),
      rendered.body.indexOf('data-testid="donor-identity-not-combined-candidates"')
    );

    expect(rendered.body).toContain('not combined');
    expect(rendered.body).toContain('possible_match');
    expect(rendered.body).toContain('JANE SMYTH');
    expect(rendered.body).toContain('these are the same person');
    expect(rendered.body).toContain('Correction submission is not yet available');
    expect(rendered.body).toContain(
      'aria-describedby="donor-identity-evidence-0-candidate-0-correction-reason"'
    );
    expect(rendered.body).toContain(
      'id="donor-identity-evidence-0-candidate-0-correction-reason"'
    );
    expect(combinedRecordList).not.toContain('JANE SMYTH');
    expect(countOccurrences(combinedRecordList, 'data-testid="donor-identity-underlying-record"')).toBe(2);
    expect(countOccurrences(rendered.body, 'data-testid="donor-identity-not-combined-candidate"')).toBe(1);
    expect(rendered.body).toContain('href="https://example.org/fec/donor-search/near-miss"');
  });

  it('withholds combined identity evidence with an explicit state when a filing URL is missing', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({
          results: [
            resolvedResult('match', {
              underlying_records: [
                underlyingRecordFixture('missing-url', {
                  sources: [{ ...sourceFixture('missing-url'), record_url: null }]
                }),
                underlyingRecordFixture('b')
              ]
            })
          ]
        })
      }
    });

    expect(rendered.body).toContain(
      'Identity evidence is unavailable because its source filing could not be verified.'
    );
    expect(rendered.body).toContain('data-testid="donor-identity-evidence-unavailable"');
    expect(rendered.body).not.toContain('data-testid="donor-identity-disclosure"');
    expect(rendered.body).not.toContain('JANE SMITH missing-url');
  });

  it('withholds an unsafe candidate while retaining valid combined identity evidence', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({
          results: [
            resolvedResult('match', {
              not_combined_candidates: [
                notCombinedCandidateFixture('unsafe-url', {
                  sources: [
                    {
                      ...sourceFixture('unsafe-url'),
                      record_url: 'javascript:alert("unsafe")'
                    }
                  ]
                })
              ]
            })
          ]
        })
      }
    });

    expect(rendered.body).toContain(
      'Identity evidence is unavailable because its source filing could not be verified.'
    );
    expect(rendered.body).toContain('data-testid="donor-candidate-evidence-unavailable"');
    expect(rendered.body).toContain('data-testid="donor-identity-disclosure"');
    expect(rendered.body).not.toContain('data-testid="donor-identity-not-combined-candidate"');
    expect(rendered.body).not.toContain('JANE SMITH unsafe-url');
  });

  it('preserves safe near-miss candidates when a sibling filing URL is unsafe', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({
          results: [
            resolvedResult('match', {
              not_combined_candidates: [
                notCombinedCandidateFixture('safe-near-miss'),
                notCombinedCandidateFixture('unsafe-near-miss', {
                  sources: [
                    {
                      ...sourceFixture('unsafe-near-miss'),
                      record_url: 'javascript:alert("unsafe")'
                    }
                  ]
                })
              ]
            })
          ]
        })
      }
    });

    expect(rendered.body).toContain('data-testid="donor-identity-not-combined-candidates"');
    expect(countOccurrences(rendered.body, 'data-testid="donor-identity-not-combined-candidate"')).toBe(1);
    expect(rendered.body).toContain('JANE SMITH safe-near-miss');
    expect(rendered.body).toContain(
      'href="https://example.org/fec/donor-search/safe-near-miss"'
    );
    expect(rendered.body).not.toContain('JANE SMITH unsafe-near-miss');
    expect(rendered.body).toContain('data-testid="donor-candidate-evidence-unavailable"');
  });

  it('renders zero-results copy without a table', () => {
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({ results: [] })
      }
    });

    expect(rendered.body).toContain('No donors match this search.');
    expect(rendered.body).toContain('data-testid="donor-freshness-stamp"');
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

  // Recipient names come from cf.candidate.name — the raw FEC filing string.
  // The three tests below pin the identity-gated owner (formatCandidatePublicName)
  // on the recipient link text. The specimens are ALL-CAPS on purpose: the
  // fixture default 'Alpha Officeholder' is already cased, so it passes through
  // the formatter unchanged and can never prove formatting happened.
  it('formats an identity-safe ALL-CAPS recipient name through the shared owner', () => {
    const base = unresolvedResult();
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({
          results: [
            {
              ...base,
              recipients: [
                {
                  ...base.recipients[0],
                  candidate_name: 'OSSOFF, T. JONATHAN',
                  identity_is_safe: true
                }
              ]
            }
          ]
        })
      }
    });

    expect(rendered.body).toContain('>Ossoff, T. Jonathan</a>');
    expect(rendered.body).not.toContain('OSSOFF, T. JONATHAN');
  });

  it('renders an identity-unsafe recipient name as the raw filed string', () => {
    const base = unresolvedResult();
    const rendered = render(DonorPage, {
      props: {
        data: donorResponse({
          results: [
            {
              ...base,
              recipients: [
                {
                  ...base.recipients[0],
                  // Address-like FEC source string; digits mark it identity-unsafe.
                  candidate_name: '212 MAIN AVE W. JOHN, RODNEY',
                  identity_is_safe: false
                }
              ]
            }
          ]
        })
      }
    });

    expect(rendered.body).toContain('>212 MAIN AVE W. JOHN, RODNEY</a>');
    expect(rendered.body).not.toContain('212 Main Ave W. John, Rodney');
  });
});
