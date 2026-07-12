import { describe, expect, it, vi } from 'vitest';
import { buildDonorSearchPath } from '$lib/donors/contract';
import { fetchDonorSearch } from './donor-search';

describe('fetchDonorSearch', () => {
  it('delegates donor search requests through the shared API client', async () => {
    const response = {
      query: 'Jane',
      by: 'name',
      limit: 20,
      offset: 0,
      results: []
    };
    const requestJson = vi.fn().mockResolvedValue(response);
    const params = { q: 'Jane', by: 'name', limit: 20, offset: 0 };

    await expect(fetchDonorSearch({ requestJson }, params)).resolves.toBe(response);

    expect(requestJson).toHaveBeenCalledWith(buildDonorSearchPath(params));
  });
});
