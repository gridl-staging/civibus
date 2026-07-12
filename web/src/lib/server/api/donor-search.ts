import { buildDonorSearchPath, type DonorSearchPathParams, type DonorSearchResponse } from '$lib/donors/contract';
import type { ApiClient } from './client';

export async function fetchDonorSearch(
  apiClient: ApiClient,
  params: DonorSearchPathParams
): Promise<DonorSearchResponse> {
  return apiClient.requestJson<DonorSearchResponse>(buildDonorSearchPath(params));
}
