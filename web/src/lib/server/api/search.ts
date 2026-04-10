import { buildSearchPath, type SearchApiResult, type SearchPathParams } from '$lib/search/contract';
import type { ApiClient } from './client';

export async function fetchSearchResults(
  apiClient: ApiClient,
  params: SearchPathParams
): Promise<SearchApiResult[]> {
  return apiClient.requestJson<SearchApiResult[]>(buildSearchPath(params));
}
