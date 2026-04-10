import { describe, expect, it } from 'vitest';
import { getApiBaseUrl, getApiRequestHeaders } from './config';

describe('getApiBaseUrl', () => {
  it('throws when the backend base URL env var is missing', () => {
    expect(() => getApiBaseUrl({})).toThrow(/CIVIBUS_API_BASE_URL/);
  });

  it('throws when the backend base URL env var is invalid', () => {
    expect(() => getApiBaseUrl({ CIVIBUS_API_BASE_URL: 'not-a-url' })).toThrow(
      /Invalid backend base URL/
    );
  });

  it('normalizes the configured URL to backend origin only', () => {
    const url = getApiBaseUrl({
      CIVIBUS_API_BASE_URL: 'https://api.civibus.local:8443/v1/search?debug=1'
    });

    expect(url).toBe('https://api.civibus.local:8443');
  });
});

describe('getApiRequestHeaders', () => {
  it('returns an empty header object when no API key is configured', () => {
    expect(getApiRequestHeaders({})).toEqual({});
  });

  it('returns X-API-Key when the API key env var is configured', () => {
    expect(
      getApiRequestHeaders({
        CIVIBUS_API_KEY: 'frontend-key'
      })
    ).toEqual({ 'X-API-Key': 'frontend-key' });
  });
});
