import { ApiResponseError } from '$lib/server/api/client';
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

describe('/search +page.server load', () => {
  it('returns blank search state without backend calls', async () => {
    const requestJson = vi.fn();

    const data = await load(createLoadEvent('https://web.civibus.local/search', requestJson));

    expect(data).toEqual({
      query: '',
      entityType: '',
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
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('delegates populated requests through event.locals.api', async () => {
    const requestJson = vi.fn().mockResolvedValue([
      {
        entity_type: 'org',
        entity_id: '22222222-2222-4222-8222-222222222222',
        name: 'Civibus Org'
      }
    ]);

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?q=civ&entity_type=org', requestJson)
    );

    expect(data).toEqual({
      query: 'civ',
      entityType: 'org',
      results: [
        {
          entity_type: 'org',
          entity_id: '22222222-2222-4222-8222-222222222222',
          name: 'Civibus Org'
        }
      ]
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=org');
  });

  it('keeps backend 422 validation errors distinct from empty successful results', async () => {
    const successfulRequestJson = vi.fn().mockResolvedValue([]);
    const successfulData = await load(
      createLoadEvent('https://web.civibus.local/search?q=ci', successfulRequestJson)
    );
    expect(successfulData).toMatchObject({
      results: []
    });

    const failedRequestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ['query', 'q'], msg: 'String should have at least 2 characters' }] })
      );

    await expect(
      load(createLoadEvent('https://web.civibus.local/search?q=c', failedRequestJson))
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ['query', 'q'], msg: 'String should have at least 2 characters' }] }
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
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ['query', 'entity_type'], msg: 'Input should be person, org, or committee' }] }
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=+civ+&entity_type=+');
  });

  it('keeps blank state when only a candidate filter is selected', async () => {
    const requestJson = vi.fn();

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?entity_type=candidate', requestJson)
    );

    expect(data).toEqual({
      query: '',
      entityType: 'candidate',
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it('forwards raw candidate entity_type params on populated queries so backend behavior stays authoritative', async () => {
    const requestJson = vi.fn().mockResolvedValue([]);

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?q=civ&entity_type=candidate', requestJson)
    );

    expect(data).toEqual({
      query: 'civ',
      entityType: 'candidate',
      results: []
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=candidate');
  });

  it('drops backend search results that the frontend cannot route safely', async () => {
    const requestJson = vi.fn().mockResolvedValue([
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
    ]);

    const data = await load(
      createLoadEvent('https://web.civibus.local/search?q=civ&entity_type=candidate', requestJson)
    );

    expect(data).toEqual({
      query: 'civ',
      entityType: 'candidate',
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
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=candidate');
  });

  it('forwards explicit empty q params so backend validation stays authoritative', async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ['query', 'q'], msg: 'String should have at least 2 characters' }] })
      );

    await expect(
      load(createLoadEvent('https://web.civibus.local/search?q=&entity_type=person', requestJson))
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ['query', 'q'], msg: 'String should have at least 2 characters' }] }
    });
    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=&entity_type=person');
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
      results: []
    });
    expect(requestJson).not.toHaveBeenCalled();
  });
});
