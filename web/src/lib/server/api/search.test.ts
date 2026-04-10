import { describe, expect, it, vi } from 'vitest';
import { fetchSearchResults } from './search';

describe('fetchSearchResults', () => {
  it('builds /v1/search query strings from shared contract params', async () => {
    const requestJson = vi.fn().mockResolvedValue([]);

    await fetchSearchResults(
      {
        requestJson
      },
      { q: 'civ', entityType: 'org' }
    );

    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=org');
  });

  it('keeps backend limit and offset defaults backend-owned', async () => {
    const requestJson = vi.fn().mockResolvedValue([]);

    await fetchSearchResults(
      {
        requestJson
      },
      { q: 'ci' }
    );

    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=ci');
  });

  it('forwards malformed non-empty entity_type values to backend validation unchanged', async () => {
    const requestJson = vi.fn().mockResolvedValue([]);

    await fetchSearchResults(
      {
        requestJson
      },
      { q: 'civ', entityType: ' ' }
    );

    expect(requestJson).toHaveBeenCalledWith('/v1/search?q=civ&entity_type=+');
  });
});
