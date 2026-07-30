import { ApiResponseError } from '$lib/server/api/client';
import { buildDonorSearchPath, type DonorSearchResponse } from '$lib/donors/contract';
import { describe, expect, it, vi } from 'vitest';
import { load } from './+page.server';

function createLoadEvent(url: string, requestJson: ReturnType<typeof vi.fn>) {
  return {
    url: new URL(url),
    locals: {
      api: {
        requestJson
      }
    }
  } as unknown as Parameters<typeof load>[0];
}

function emptyResponse(params: Partial<DonorSearchResponse> = {}): DonorSearchResponse {
  return {
    query: 'Jane',
    by: 'name',
    limit: 20,
    offset: 0,
    results: [],
    ...params
  };
}

const source = {
  domain: 'campaign_finance',
  jurisdiction: 'federal/fec',
  data_source_name: 'FEC filing',
  data_source_url: 'https://www.fec.gov/data/',
  source_record_key: 'filing-1',
  record_url: 'https://www.fec.gov/data/receipts/?data_type=processed',
  pull_date: '2026-07-09T12:00:00Z'
};

describe('/donors +page.server load', () => {
  it('returns untouched empty state without backend calls', async () => {
    const requestJson = vi.fn();

    await expect(load(createLoadEvent('https://web.civibus.local/donors', requestJson))).resolves.toEqual({
      query: '',
      by: 'name',
      limit: 20,
      offset: 0,
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('treats whitespace-only q as untouched empty state without backend calls', async () => {
    const requestJson = vi.fn();

    await expect(
      load(createLoadEvent('https://web.civibus.local/donors?q=%20%20&by=name', requestJson))
    ).resolves.toEqual({
      query: '',
      by: 'name',
      limit: 20,
      offset: 0,
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('short-circuits short name searches without backend calls', async () => {
    const requestJson = vi.fn();

    await expect(
      load(createLoadEvent('https://web.civibus.local/donors?q=Ja&by=name', requestJson))
    ).resolves.toEqual({
      query: 'Ja',
      by: 'name',
      limit: 20,
      offset: 0,
      results: [],
      shortQueryGuidance: true
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('delegates populated requests through event.locals.api', async () => {
    const response = emptyResponse({
      query: 'Jane',
      results: [
        {
          id: '72000000-0000-0000-0000-000000000101',
          donor_identity_id: '72100000-0000-0000-0000-000000000001',
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
          confidence_band: 'match',
          recipients: [],
          sources: [source],
          underlying_records: [
            {
              donor_identity_id: '72100000-0000-0000-0000-000000000001',
              contributor_name: 'JANE SMITH',
              contributor_employer: 'Civibus Labs',
              contributor_occupation: 'Engineer',
              contributor_city: 'Durham',
              contributor_state: 'NC',
              normalized_zip5: '27701',
              sources: [source]
            }
          ],
          not_combined_candidates: [
            {
              donor_identity_id: '72100000-0000-0000-0000-000000000002',
              contributor_name: 'JANE SMYTH',
              contributor_employer: 'Civibus Labs',
              contributor_occupation: 'Engineer',
              contributor_city: 'Durham',
              contributor_state: 'NC',
              normalized_zip5: '27701',
              confidence_band: 'possible_match',
              sources: [source]
            }
          ]
        }
      ]
    });
    const requestJson = vi.fn().mockResolvedValue(response);

    await expect(
      load(createLoadEvent('https://web.civibus.local/donors?q=Jane&by=name', requestJson))
    ).resolves.toEqual(response);
    expect(requestJson).toHaveBeenCalledWith(
      buildDonorSearchPath({ q: 'Jane', by: 'name', limit: 20, offset: 0 })
    );
  });

  it('rejects a successful backend response that drifts from the donor contract', async () => {
    const response = {
      query: 'Jane',
      by: 'name',
      limit: 20,
      offset: 0,
      results: [
        {
          id: '72000000-0000-0000-0000-000000000101',
          contributor_name: 'JANE SMITH',
          total_amount: '500.00'
        }
      ]
    };
    const requestJson = vi.fn().mockResolvedValue(response);

    await expect(
      load(createLoadEvent('https://web.civibus.local/donors?q=Jane&by=name', requestJson))
    ).rejects.toThrow('results[0].donor_identity_id must be a string or null.');
  });

  it.each([
    [
      { detail: 'Unsupported donor search mode: bogus' },
      'Choose a search mode: name, employer, or ZIP.'
    ],
    [
      { detail: 'Donor name searches require at least 3 characters' },
      'Enter at least 3 characters to search by name or employer.'
    ],
    [
      { detail: 'Donor ZIP searches require a 5-digit ZIP or ZIP+4 query' },
      'Enter a 5-digit ZIP or ZIP+4 to search by ZIP.'
    ]
  ])('translates known 422 validation body %# into inline copy', async (body, validationMessage) => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(422, body));

    await expect(
      load(createLoadEvent('https://web.civibus.local/donors?q=Jane&by=bogus', requestJson))
    ).resolves.toEqual({
      query: 'Jane',
      by: 'bogus',
      limit: 20,
      offset: 0,
      results: [],
      validationMessage
    });
  });

  it('re-raises non-422 API failures through the shared route error mapper', async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(503, 'Backend unavailable'));

    await expect(
      load(createLoadEvent('https://web.civibus.local/donors?q=Jane&by=name', requestJson))
    ).rejects.toMatchObject({
      status: 503,
      body: { message: 'Backend unavailable' }
    });
  });
});
