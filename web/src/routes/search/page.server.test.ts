import { ApiResponseError } from '$lib/server/api/client';
import { buildWashingtonNode } from '$lib/regional-navigation/test-fixtures';
import { buildSearchPagePath } from '$lib/search/contract';
import { describe, expect, it, vi } from 'vitest';
import { actions, load } from './+page.server';

function createLoadEvent(
  url: string,
  requestJson: ReturnType<typeof vi.fn<(path: string) => unknown>>,
  regionalResponse: unknown = {
    items: [],
    incomplete_node_kinds: [],
    has_unsafe_omissions: false
  }
) {
  const navigationAwareRequest = vi.fn(async (path: string) => {
    if (path.startsWith('/v1/regional-navigation/search?')) return regionalResponse;
    return requestJson(path);
  });
  return {
    url: new URL(url),
    locals: {
      api: {
        requestJson: navigationAwareRequest
      }
    }
  } as unknown as Parameters<typeof load>[0];
}

function createActionEvent(
  formValues: { q?: string; entity_type?: string },
  requestJson: ReturnType<typeof vi.fn>
) {
  const formData = new FormData();

  if (formValues.q !== undefined) {
    formData.set('q', formValues.q);
  }

  if (formValues.entity_type !== undefined) {
    formData.set('entity_type', formValues.entity_type);
  }

  return {
    request: new Request('https://web.civibus.local/search', { method: 'POST', body: formData }),
    locals: {
      api: {
        requestJson
      }
    }
  } as unknown as Parameters<NonNullable<typeof actions.default>>[0];
}

function createActionEventFromFormData(formData: FormData, requestJson: ReturnType<typeof vi.fn>) {
  return {
    request: new Request('https://web.civibus.local/search', { method: 'POST', body: formData }),
    locals: {
      api: {
        requestJson
      }
    }
  } as unknown as Parameters<NonNullable<typeof actions.default>>[0];
}

describe('/search +page.server load', () => {
  it('returns blank search state without backend calls', async () => {
    const requestJson = vi.fn();

    const data = await load(createLoadEvent('https://web.civibus.local/search', requestJson));

    expect(data).toEqual({
      query: '',
      entityType: '',
      offset: 0,
      hasNext: false,
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('keeps blank state when only a valid entity filter is selected', async () => {
    const requestJson = vi.fn();

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?entity_type=person', requestJson)
    );

    expect(data).toEqual({
      query: '',
      entityType: 'person',
      offset: 0,
      hasNext: false,
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('delegates populated requests through event.locals.api', async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [
        {
          entity_type: 'org',
          entity_id: '22222222-2222-4222-8222-222222222222',
          name: 'Civibus Org'
        }
      ],
      has_next: false
    });

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?q=civ&entity_type=org', requestJson)
    );

    expect(data).toEqual({
      query: 'civ',
      entityType: 'org',
      offset: 0,
      hasNext: false,
      results: [
        {
          entity_type: 'org',
          entity_id: '22222222-2222-4222-8222-222222222222',
          name: 'Civibus Org'
        }
      ]
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=org&limit=20');
  });

  it('adds only shared canonical regional results to an unfiltered first page', async () => {
    const requestJson = vi.fn().mockResolvedValue({ items: [], has_next: false });
    const regionalResponse = {
      items: [buildWashingtonNode()],
      incomplete_node_kinds: ['county', 'municipality'],
      has_unsafe_omissions: true
    };

    const data = await load(
      createLoadEvent(
        'https://web.civibus.local/search?q=Washington',
        requestJson,
        regionalResponse
      )
    );
    if (!data) throw new Error('Expected search page data.');

    expect(data).toMatchObject({
      results: [],
      regionalResults: [
        {
          kind: 'state',
          canonical_path: '/state/WA'
        }
      ],
      regionalIncompleteNodeKinds: ['county', 'municipality'],
      regionalHasUnsafeOmissions: true
    });
    expect(data.regionalResults[0].finance_detail?.sources[0]?.name).toBe(
      'WA PDC Contributions'
    );
    expect(data.regionalResults[0].finance_detail?.money[0]).toMatchObject({
      key: 'contributions',
      amount: '125.50'
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      '/v1/search?q=Washington&limit=20'
    ]);
  });

  it('uses the shared regional endpoint without calling legacy search for the Region filter', async () => {
    const requestJson = vi.fn();
    const regionalResponse = {
      items: [],
      incomplete_node_kinds: ['county', 'municipality'],
      has_unsafe_omissions: true
    };

    const data = await load(
      createLoadEvent(
        'https://web.civibus.local/search?q=San+Francisco&entity_type=region',
        requestJson,
        regionalResponse
      )
    );

    expect(data).toMatchObject({
      query: 'San Francisco',
      entityType: 'region',
      results: [],
      regionalIncompleteNodeKinds: ['county', 'municipality'],
      regionalHasUnsafeOmissions: true
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('canonicalizes Region-filter offsets instead of replaying its only bounded page', async () => {
    const requestJson = vi.fn();

    await expect(
      load(
        createLoadEvent(
          'https://web.civibus.local/search?q=Washington&entity_type=region&offset=20',
          requestJson
        )
      )
    ).rejects.toMatchObject({
      status: 308,
      location: '/search?q=Washington&entity_type=region'
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('trusts backend has_next and preserves every returned renderable row', async () => {
    const backendRows = Array.from({ length: 21 }, (_, index) => ({
      entity_type: 'org',
      entity_id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
      name: `Paged Org ${index}`
    }));
    const requestJson = vi.fn().mockResolvedValue({ items: backendRows, has_next: false });

    const data = (await load(
      createLoadEvent('https://web.civibus.local/search?q=paged', requestJson)
    )) as { results: Array<{ name: string }>; hasNext: boolean; offset: number };

    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=paged&limit=20');
    expect(data.results).toHaveLength(21);
    expect(data.results.map((row) => row.name)).toContain('Paged Org 20');
    expect(data.hasNext).toBe(false);
    expect(data.offset).toBe(0);
  });

  it('passes the URL offset through to the backend and reports the accepted position', async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [
        {
          entity_type: 'org',
          entity_id: '00000000-0000-4000-8000-000000000099',
          name: 'Last Page Org'
        }
      ],
      has_next: false
    });

    const data = (await load(
      createLoadEvent('https://web.civibus.local/search?q=paged&offset=20', requestJson)
    )) as { results: unknown[]; hasNext: boolean; offset: number };

    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=paged&limit=20&offset=20');
    expect(data.hasNext).toBe(false);
    expect(data.offset).toBe(20);
    expect(data.results).toHaveLength(1);
  });

  it.each(['9007199254740993', '9007199254740972'])(
    'fails closed when backend-accepted offset %s cannot support exact web pagination arithmetic',
    async (rawOffset) => {
      const requestJson = vi.fn().mockResolvedValue({
        items: [
          {
            entity_type: 'org',
            entity_id: '00000000-0000-4000-8000-000000000099',
            name: 'Unsafe Page Org'
          }
        ],
        has_next: true
      });

      const data = await load(
        createLoadEvent(
          `https://web.civibus.local/search?q=paged&entity_type=org&offset=${rawOffset}`,
          requestJson
        )
      );

      expect(requestJson).toHaveBeenCalledWith(
        `/v1/search?q=paged&entity_type=org&limit=20&offset=${rawOffset}`
      );
      expect(data).toEqual({
        query: 'paged',
        entityType: 'org',
        offset: 0,
        hasNext: false,
        results: [],
        hasUnavailableResultPage: true,
        validationMessage:
          'The requested search page is too large to navigate safely. Submit the search to return to the first page.'
      });
    }
  );

  it('includes returned-row headroom in the exact maximum supported offset', async () => {
    const rawOffset = String(Number.MAX_SAFE_INTEGER - 20);
    const backendRows = Array.from({ length: 21 }, (_, index) => ({
      entity_type: 'org',
      entity_id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
      name: `Boundary Org ${index}`
    }));
    const exactRequestJson = vi.fn().mockResolvedValue({
      items: backendRows.slice(0, 20),
      has_next: true
    });
    const overflowRequestJson = vi.fn().mockResolvedValue({ items: backendRows, has_next: true });

    const exactData = (await load(
      createLoadEvent(`https://web.civibus.local/search?q=paged&offset=${rawOffset}`, exactRequestJson)
    )) as { offset: number; results: unknown[]; validationMessage?: string };
    const overflowData = await load(
      createLoadEvent(
        `https://web.civibus.local/search?q=paged&offset=${rawOffset}`,
        overflowRequestJson
      )
    );

    expect(exactData.offset).toBe(Number.MAX_SAFE_INTEGER - 20);
    expect(exactData.results).toHaveLength(20);
    expect(exactData.validationMessage).toBeUndefined();
    expect(overflowData).toEqual({
      query: 'paged',
      entityType: '',
      offset: 0,
      hasNext: false,
      results: [],
      hasUnavailableResultPage: true,
      validationMessage:
        'The requested search page is too large to navigate safely. Submit the search to return to the first page.'
    });
  });

  it('keeps backend 422 validation errors distinct from empty successful results', async () => {
    const successfulRequestJson = vi.fn().mockResolvedValue({ items: [], has_next: false });
    const successfulData = await load(
      createLoadEvent('https://web.civibus.local/search?q=ci', successfulRequestJson)
    );
    expect(successfulData).toMatchObject({
      offset: 0,
      hasNext: false,
      results: []
    });

    const failedRequestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ['query', 'q'], msg: 'String should have at least 2 characters' }] })
      );

    await expect(load(createLoadEvent('https://web.civibus.local/search?q=c', failedRequestJson))).resolves.toEqual({
      query: 'c',
      entityType: '',
      offset: 0,
      hasNext: false,
      results: [],
      validationMessage: 'query.q: String should have at least 2 characters'
    });
  });

  it('falls back to default inline validation copy when backend 422 does not include a readable payload', async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(422, null));

    await expect(load(createLoadEvent('https://web.civibus.local/search?q=c', requestJson))).resolves.toEqual({
      query: 'c',
      entityType: '',
      offset: 0,
      hasNext: false,
      results: [],
      validationMessage: 'The search request could not be validated. Review your query and try again.'
    });
  });

  it('preserves raw query params so backend validation sees whitespace-only filters unchanged', async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ['query', 'entity_type'], msg: 'Input should be person, org, or committee' }] })
      );

    await expect(
      load(createLoadEvent('https://web.civibus.local/search?q=%20civ%20&entity_type=%20', requestJson))
    ).resolves.toEqual({
      query: ' civ ',
      entityType: ' ',
      offset: 0,
      hasNext: false,
      results: [],
      validationMessage: 'query.entity_type: Input should be person, org, or committee'
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=+civ+&entity_type=+&limit=20');
  });

  it('keeps blank state when only a candidate filter is selected', async () => {
    const requestJson = vi.fn();

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?entity_type=candidate', requestJson)
    );

    expect(data).toEqual({
      query: '',
      entityType: 'candidate',
      offset: 0,
      hasNext: false,
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('keeps blank state when only a contest filter is selected', async () => {
    const requestJson = vi.fn();

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?entity_type=contest', requestJson)
    );

    expect(data).toEqual({
      query: '',
      entityType: 'contest',
      offset: 0,
      hasNext: false,
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('forwards raw candidate entity_type params on populated queries so backend behavior stays authoritative', async () => {
    const requestJson = vi.fn().mockResolvedValue({ items: [], has_next: false });

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?q=civ&entity_type=candidate', requestJson)
    );

    expect(data).toEqual({
      query: 'civ',
      entityType: 'candidate',
      offset: 0,
      hasNext: false,
      results: []
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=candidate&limit=20');
  });

  it('drops backend search results that the frontend cannot route safely', async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [
        {
          entity_type: 'candidate',
          entity_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          name: 'Candidate UUID'
        },
        {
          entity_type: 'candidate',
          entity_id: 'H0NC01001',
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
      ],
      has_next: false
    });

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?q=civ&entity_type=candidate', requestJson)
    );

    expect(data).toEqual({
      query: 'civ',
      entityType: 'candidate',
      offset: 0,
      hasNext: false,
      hasUnrenderableResults: true,
      results: [
        {
          entity_type: 'candidate',
          entity_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          name: 'Candidate UUID'
        },
        {
          entity_type: 'office',
          entity_id: '44444444-4444-4444-8444-444444444444',
          name: 'Governor'
        }
      ]
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=candidate&limit=20');
  });

  it('preserves backend page navigation when filtering destroys displayed row positions', async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [
        {
          entity_type: 'legacy',
          entity_id: 'not-routable',
          name: 'Backend row 21'
        },
        {
          entity_type: 'org',
          entity_id: '22222222-2222-4222-8222-222222222222',
          name: 'Backend row 22'
        }
      ],
      has_next: true
    });

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?q=civ&entity_type=org&offset=20', requestJson)
    );

    expect(data).toEqual({
      query: 'civ',
      entityType: 'org',
      offset: 20,
      hasNext: true,
      hasUnrenderableResults: true,
      results: [
        {
          entity_type: 'org',
          entity_id: '22222222-2222-4222-8222-222222222222',
          name: 'Backend row 22'
        }
      ]
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=org&limit=20&offset=20');
  });

  it('preserves when every backend match is unsafe to route', async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [
        {
          entity_type: 'candidate',
          entity_id: 'H0NC01001',
          name: 'Pat Candidate'
        },
        {
          entity_type: 'person',
          entity_id: 'not-a-uuid',
          name: 'Alice'
        }
      ],
      has_next: false
    });

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?q=civ', requestJson)
    );

    expect(data).toEqual({
      query: 'civ',
      entityType: '',
      offset: 0,
      hasNext: false,
      hasUnrenderableResults: true,
      results: []
    });
  });

  it('forwards explicit empty q params so backend validation stays authoritative', async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ['query', 'q'], msg: 'String should have at least 2 characters' }] })
      );

    await expect(
      load(createLoadEvent('https://web.civibus.local/search?q=&entity_type=person', requestJson))
    ).resolves.toEqual({
      query: '',
      entityType: 'person',
      offset: 0,
      hasNext: false,
      results: [],
      validationMessage: 'query.q: String should have at least 2 characters'
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=&entity_type=person&limit=20');
  });

  it('keeps shared route error handling for backend 404 responses', async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(404, 'Search endpoint not found'));

    await expect(
      load(createLoadEvent('https://web.civibus.local/search?q=civ', requestJson))
    ).rejects.toMatchObject({
      status: 404,
      body: { message: 'Search endpoint not found' }
    });
  });

  it('keeps shared route error handling for backend 500 responses', async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(new ApiResponseError(500, { detail: [{ loc: ['server'], msg: 'Unexpected failure' }] }));

    await expect(
      load(createLoadEvent('https://web.civibus.local/search?q=civ', requestJson))
    ).rejects.toMatchObject({
      status: 500,
      body: { detail: [{ loc: ['server'], msg: 'Unexpected failure' }] }
    });
  });

  it('preserves backend plain-text failures through the shared route error mapper', async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(503, 'Backend unavailable'));

    await expect(
      load(createLoadEvent('https://web.civibus.local/search?q=civ', requestJson))
    ).rejects.toMatchObject({
      status: 503,
      body: { message: 'Backend unavailable' }
    });
  });

  // --- Office search integration contract (Stage 1 red-phase tests) ---

  it('keeps blank state when office entity filter is selected without a query', async () => {
    const requestJson = vi.fn();

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?entity_type=office', requestJson)
    );

    expect(data).toEqual({
      query: '',
      entityType: 'office',
      offset: 0,
      hasNext: false,
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });
});

describe('/search +page.server actions', () => {
  it('validates Region submits through the regional endpoint and keeps the filter in the redirect', async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [],
      incomplete_node_kinds: ['county', 'municipality'],
      has_unsafe_omissions: true
    });

    await expect(
      actions.default(createActionEvent({ q: 'Washington', entity_type: 'region' }, requestJson))
    ).rejects.toMatchObject({
      status: 303,
      location: '/search?q=Washington&entity_type=region'
    });
    expect(requestJson).toHaveBeenCalledWith(
      '/v1/regional-navigation/search?q=Washington&limit=20'
    );
  });

  it('redirects successful submits through the shared search page path builder', async () => {
    const requestJson = vi.fn().mockResolvedValue({ items: [], has_next: false });

    await expect(
      actions.default(createActionEvent({ q: 'civ', entity_type: 'org' }, requestJson))
    ).rejects.toMatchObject({
      status: 303,
      location: buildSearchPagePath({ q: 'civ', entityType: 'org' })
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=org');
  });

  it('returns inline 422 payload data and preserves raw submitted query and entity_type values', async () => {
    const requestJson = vi.fn().mockRejectedValue(
      new ApiResponseError(422, {
        detail: [
          { loc: ['query', 'q'], msg: 'String should have at least 2 characters' },
          { loc: ['query', 'entity_type'], msg: 'Input should be person, org, or committee' }
        ]
      })
    );

    const result = await actions.default(createActionEvent({ q: ' civ ', entity_type: ' ' }, requestJson));

    expect(result).toMatchObject({
      status: 422,
      data: {
        query: ' civ ',
        entityType: ' ',
        validationMessage:
          'query.q: String should have at least 2 characters; query.entity_type: Input should be person, org, or committee'
      }
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=+civ+&entity_type=+');
  });

  it('returns default inline validation copy for submit 422 errors with unreadable payloads', async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(422, null));

    const result = await actions.default(createActionEvent({ q: 'c', entity_type: 'candidate' }, requestJson));

    expect(result).toMatchObject({
      status: 422,
      data: {
        query: 'c',
        entityType: 'candidate',
        validationMessage: 'The search request could not be validated. Review your query and try again.'
      }
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=c&entity_type=candidate');
  });

  it('coerces non-string form values to empty strings before invoking backend search', async () => {
    const requestJson = vi.fn().mockResolvedValue({ items: [], has_next: false });
    const formData = new FormData();
    formData.set('q', new Blob(['query-bytes']), 'query.bin');
    formData.set('entity_type', new Blob(['type-bytes']), 'entity_type.bin');

    await expect(actions.default(createActionEventFromFormData(formData, requestJson))).rejects.toMatchObject({
      status: 303,
      location: buildSearchPagePath({ q: '', entityType: '' })
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=');
  });

  it('keeps shared API error behavior for non-422 submit failures', async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(503, 'Backend unavailable'));

    await expect(
      actions.default(createActionEvent({ q: 'civ', entity_type: 'org' }, requestJson))
    ).rejects.toMatchObject({
      status: 503,
      body: { message: 'Backend unavailable' }
    });
  });
});
