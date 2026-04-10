import { buildParcelDetailPath, type ParcelDetailResponse } from "$lib/property-detail/contract";
import type { ApiClient } from "./client";

export type ParcelDetailRequest = {
  id: string;
};

export async function fetchParcelDetail(
  apiClient: ApiClient,
  request: ParcelDetailRequest
): Promise<ParcelDetailResponse> {
  return apiClient.requestJson<ParcelDetailResponse>(buildParcelDetailPath(request.id));
}
