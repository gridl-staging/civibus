import {
  buildCandidacyDetailPath,
  buildContestDetailPath,
  buildOfficeDetailPath,
  buildOfficeholdingDetailPath,
  type CandidacyDetailResponse,
  type ContestDetailResponse,
  type OfficeDetailResponse,
  type OfficeholdingDetailResponse
} from "$lib/civic-detail/contract";
import type { ApiClient } from "./client";

export type OfficeDetailRequest = {
  id: string;
};

export type ContestDetailRequest = {
  id: string;
};

export type CandidacyDetailRequest = {
  id: string;
};

export type OfficeholdingDetailRequest = {
  id: string;
};

export async function fetchOfficeDetail(
  apiClient: ApiClient,
  request: OfficeDetailRequest
): Promise<OfficeDetailResponse> {
  return apiClient.requestJson<OfficeDetailResponse>(buildOfficeDetailPath(request.id));
}

export async function fetchContestDetail(
  apiClient: ApiClient,
  request: ContestDetailRequest
): Promise<ContestDetailResponse> {
  return apiClient.requestJson<ContestDetailResponse>(buildContestDetailPath(request.id));
}

export async function fetchCandidacyDetail(
  apiClient: ApiClient,
  request: CandidacyDetailRequest
): Promise<CandidacyDetailResponse> {
  return apiClient.requestJson<CandidacyDetailResponse>(buildCandidacyDetailPath(request.id));
}

export async function fetchOfficeholdingDetail(
  apiClient: ApiClient,
  request: OfficeholdingDetailRequest
): Promise<OfficeholdingDetailResponse> {
  return apiClient.requestJson<OfficeholdingDetailResponse>(buildOfficeholdingDetailPath(request.id));
}
