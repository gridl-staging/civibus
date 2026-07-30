import { buildDonorSearchPath, type DonorSearchPathParams } from '$lib/donors/contract';
import type { ApiClient } from './client';

export async function fetchDonorSearch(
  apiClient: ApiClient,
  params: DonorSearchPathParams
): Promise<unknown> {
  return apiClient.requestJson<unknown>(buildDonorSearchPath(params));
}
