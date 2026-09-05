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
    rollup_completed_at: '2026-07-17T12:00:00Z',
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
      rollup_completed_at: null,
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
      rollup_completed_at: null,
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
      rollup_completed_at: null,
      results: [],
      shortQueryGuidance: true
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('preserves backend-accepted signed integer text during short-query guidance', async () => {
    const requestJson = vi.fn();

    await expect(
      load(
        createLoadEvent(
          'https://web.civibus.local/donors?q=Ja&by=name&limit=%2B1&offset=0',
          requestJson
        )
      )
    ).resolves.toEqual({
      query: 'Ja',
      by: 'name',
      limit: 1,
      offset: 0,
      rollup_completed_at: null,
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

  it.each([
    ['partial limit', '20donors', '0'],
    ['exponent-like limit', '1e2', '0'],
    ['fractional offset', '20', '20.5'],
    ['partial offset', '20', '20donors'],
    ['unsafe limit', '9007199254740993', '0']
  ])(
    'forwards %s text unchanged to backend-owned validation',
    async (_label, limit, offset) => {
      const requestJson = vi.fn().mockRejectedValue(
        new ApiResponseError(422, {
          detail: [{ loc: ['query', offset === '0' ? 'limit' : 'offset'] }]
        })
      );

      await expect(
        load(
          createLoadEvent(
            `https://web.civibus.local/donors?q=Jane&by=name&limit=${limit}&offset=${offset}`,
            requestJson
          )
        )
      ).resolves.toEqual({
        query: 'Jane',
        by: 'name',
        limit: 20,
        offset: 0,
        rollup_completed_at: null,
        results: [],
        validationMessage:
          'The donor search request could not be validated. Review your query and try again.'
      });
      expect(requestJson).toHaveBeenCalledWith(
        buildDonorSearchPath({ q: 'Jane', by: 'name', limit, offset })
      );
    }
  );

  it.each([
    ['limit below minimum', '0', '0'],
    ['limit above maximum', '51', '0'],
    ['negative offset', '20', '-1']
  ])('leaves %s enforcement with the backend owner', async (_label, limit, offset) => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(422, { detail: [] }));

    await load(
      createLoadEvent(
        `https://web.civibus.local/donors?q=Jane&by=name&limit=${limit}&offset=${offset}`,
        requestJson
      )
    );

    expect(requestJson).toHaveBeenCalledWith(
      buildDonorSearchPath({ q: 'Jane', by: 'name', limit, offset })
    );
  });

  it.each(['9007199254740993', '9007199254740972'])(
    'fails closed after backend acceptance when offset %s cannot support exact web pagination',
    async (rawOffset) => {
      const response = emptyResponse({
        offset: Number(rawOffset),
        results: []
      });
      const requestJson = vi.fn().mockResolvedValue(response);

      await expect(
        load(
          createLoadEvent(
            `https://web.civibus.local/donors?q=Jane&by=name&limit=20&offset=${rawOffset}`,
            requestJson
          )
        )
      ).resolves.toEqual({
        query: 'Jane',
        by: 'name',
        limit: 20,
        offset: 0,
        rollup_completed_at: null,
        results: [],
        validationMessage:
          'The requested donor page could not be displayed safely. Submit the search to return to the first page.'
      });
      expect(requestJson).toHaveBeenCalledWith(
        buildDonorSearchPath({ q: 'Jane', by: 'name', limit: '20', offset: rawOffset })
      );
    }
  );

  it.each([
    ['limit', { limit: 21, offset: 20 }],
    ['offset', { limit: 20, offset: 21 }]
  ])('fails closed when a successful response changes the requested %s', async (_field, drift) => {
    const response = emptyResponse(drift);
    const requestJson = vi.fn().mockResolvedValue(response);

    await expect(
      load(
        createLoadEvent(
          'https://web.civibus.local/donors?q=Jane&by=name&limit=20&offset=20',
          requestJson
        )
      )
    ).resolves.toEqual({
      query: 'Jane',
      by: 'name',
      limit: 20,
      offset: 0,
      rollup_completed_at: null,
      results: [],
      validationMessage:
        'The requested donor page could not be displayed safely. Submit the search to return to the first page.'
    });
    expect(requestJson).toHaveBeenCalledWith(
      buildDonorSearchPath({ q: 'Jane', by: 'name', limit: '20', offset: '20' })
    );
  });

  it('keeps the exact safe-integer pagination headroom boundary available', async () => {
    const rawOffset = String(Number.MAX_SAFE_INTEGER - 20);
    const response = emptyResponse({ offset: Number(rawOffset), results: [] });
    const requestJson = vi.fn().mockResolvedValue(response);

    await expect(
      load(
        createLoadEvent(
          `https://web.civibus.local/donors?q=Jane&by=name&limit=20&offset=${rawOffset}`,
          requestJson
        )
      )
    ).resolves.toEqual(response);
    expect(requestJson).toHaveBeenCalledWith(
      buildDonorSearchPath({ q: 'Jane', by: 'name', limit: '20', offset: rawOffset })
    );
  });

  it.each([
    ['minimum', '1', '0'],
    ['maximum', '50', '50']
  ])(
    'preserves the backend-owned accepted limit %s and safe page offsets',
    async (_label, limit, offset) => {
      const response = emptyResponse({ limit: Number(limit), offset: Number(offset) });
      const requestJson = vi.fn().mockResolvedValue(response);

      await expect(
        load(
          createLoadEvent(
            `https://web.civibus.local/donors?q=Jane&by=name&limit=${limit}&offset=${offset}`,
            requestJson
          )
        )
      ).resolves.toEqual(response);
      expect(requestJson).toHaveBeenCalledWith(
        buildDonorSearchPath({ q: 'Jane', by: 'name', limit, offset })
      );
    }
  );

  it('rejects a successful backend response that drifts from the donor contract', async () => {
    const response = {
      query: 'Jane',
      by: 'name',
      limit: 20,
      offset: 0,
      rollup_completed_at: '2026-07-17T12:00:00Z',
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
      rollup_completed_at: null,
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

  it('preserves the exact rollup-unavailable 503 through the shared error boundary', async () => {
    const body = {
      detail: {
        code: 'donor_search_rollup_unavailable'
      }
    };
    const requestJson = vi.fn().mockRejectedValue(
      new ApiResponseError(503, body)
    );

    await expect(
      load(createLoadEvent('https://web.civibus.local/donors?q=Williams&by=name', requestJson))
    ).rejects.toMatchObject({
      status: 503,
      body
    });
  });
});
