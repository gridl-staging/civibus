import { describe, expect, it, vi } from 'vitest';
import { createApiClient, requestJson } from './client';
import { getApiErrorDisplayMessage } from './error';

describe('api client', () => {
  it('defers backend base URL lookup until a request is made', async () => {
    const missingEnvError = new Error('Missing required environment variable: CIVIBUS_API_BASE_URL');
    const client = createApiClient({
      baseUrl() {
        throw missingEnvError;
      },
      fetch: vi.fn()
    });

    await expect(client.requestJson('/v1/search')).rejects.toBe(missingEnvError);
  });

  it('joins relative /v1 paths against the configured backend origin', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => {
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' }
        });
      }
    );

    const client = createApiClient({
      baseUrl: 'https://api.civibus.local',
      fetch: fetchMock
    });

    await client.requestJson('/v1/search?query=parks');

    const calledUrl = String(fetchMock.mock.lastCall?.[0] ?? '');
    expect(calledUrl).toBe('https://api.civibus.local/v1/search?query=parks');
  });

  it('adds configured default headers to backend requests', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => {
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' }
        });
      }
    );

    const client = createApiClient({
      baseUrl: 'https://api.civibus.local',
      defaultHeaders: { 'X-API-Key': 'frontend-key' },
      fetch: fetchMock
    });

    await client.requestJson('/v1/search?query=parks');

    const calledHeaders = new Headers(fetchMock.mock.lastCall?.[1]?.headers);
    expect(calledHeaders.get('X-API-Key')).toBe('frontend-key');
  });

  it('lets per-request headers override default headers', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => {
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' }
        });
      }
    );

    const client = createApiClient({
      baseUrl: 'https://api.civibus.local',
      defaultHeaders: { 'X-API-Key': 'frontend-key' },
      fetch: fetchMock
    });

    await client.requestJson('/v1/search?query=parks', {
      headers: {
        'X-API-Key': 'override-key',
        'X-Request-ID': 'request-123'
      }
    });

    const calledHeaders = new Headers(fetchMock.mock.lastCall?.[1]?.headers);
    expect(calledHeaders.get('X-API-Key')).toBe('override-key');
    expect(calledHeaders.get('X-Request-ID')).toBe('request-123');
  });

  it('rejects ad-hoc absolute URLs', async () => {
    const fetchMock = vi.fn();

    await expect(
      requestJson({
        baseUrl: 'https://api.civibus.local',
        fetch: fetchMock,
        path: 'https://malicious.example/v1/search'
      })
    ).rejects.toThrow(/relative \/v1 path/);
  });

  it('rejects paths that escape or mimic the /v1 contract', async () => {
    const fetchMock = vi.fn();
    const invalidPaths = [
      '/v1/../health',
      '/v1/%2e%2e/health',
      '/v1/.%2e/health',
      '/v1/person/../search',
      '/v1/person/%2e%2e/search',
      '/v1/person/..%2Fsearch',
      '/v1x/search'
    ];

    for (const path of invalidPaths) {
      await expect(
        requestJson({
          baseUrl: 'https://api.civibus.local',
          fetch: fetchMock,
          path
        })
      ).rejects.toThrow(/relative \/v1 path/);
    }
  });

  it('preserves backend 404 JSON response bodies', async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(JSON.stringify({ detail: 'Not found' }), {
        status: 404,
        headers: { 'content-type': 'application/json' }
      });
    });

    await expect(
      requestJson({
        baseUrl: 'https://api.civibus.local',
        fetch: fetchMock,
        path: '/v1/entities/missing'
      })
    ).rejects.toMatchObject({
      status: 404,
      body: { detail: 'Not found' }
    });
  });

  it('preserves backend 422 JSON response bodies', async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(JSON.stringify({ detail: [{ loc: ['query', 'q'], msg: 'required' }] }), {
        status: 422,
        headers: { 'content-type': 'application/json' }
      });
    });

    await expect(
      requestJson({
        baseUrl: 'https://api.civibus.local',
        fetch: fetchMock,
        path: '/v1/search'
      })
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ['query', 'q'], msg: 'required' }] }
    });
  });
});

describe('api error display message', () => {
  it('prefers backend string detail payloads over generic fallback copy', () => {
    expect(getApiErrorDisplayMessage({ detail: 'Person not found' } as unknown as App.Error)).toBe(
      'Person not found'
    );
  });

  it('formats backend validation detail arrays for the shared error page', () => {
    expect(
      getApiErrorDisplayMessage({
        detail: [
          { loc: ['query', 'q'], msg: 'String should have at least 2 characters' },
          { loc: ['query', 'entity_type'], msg: 'Input should be person, org, or committee' }
        ]
      } as unknown as App.Error)
    ).toBe(
      'query.q: String should have at least 2 characters; query.entity_type: Input should be person, org, or committee'
    );
  });

  it('falls back to the top-level error message when no backend detail exists', () => {
    expect(getApiErrorDisplayMessage({ message: 'Backend unavailable' } as App.Error)).toBe(
      'Backend unavailable'
    );
  });
});
