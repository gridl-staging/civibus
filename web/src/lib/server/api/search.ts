import { buildSearchPath, type SearchApiResponse, type SearchPathParams } from '$lib/search/contract';
import type { ApiClient } from './client';

export async function fetchSearchResults(
  apiClient: ApiClient,
  params: SearchPathParams
): Promise<SearchApiResponse> {
  return apiClient.requestJson<SearchApiResponse>(buildSearchPath(params));
}
