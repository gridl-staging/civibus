import {
  buildCongressMembersPath,
  buildCongressMoneySummariesPath,
  buildElectionDateAggregatePath,
  buildUpcomingElectionTimelinePath,
  buildCandidacyDetailPath,
  buildContestDetailPath,
  buildOfficeDetailPath,
  buildOfficeholdingDetailPath,
  type CongressMemberSummary,
  type CongressMemberMoneySummary,
  type CandidacyDetailResponse,
  type ContestDetailResponse,
  type ElectionDateAggregateResponse,
  type OfficeDetailResponse,
  type OfficeholdingDetailResponse,
  type UpcomingElectionTimelineEntry
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

export type ElectionDateAggregateRequest = {
  date: string;
};

export async function fetchCongressMembers(apiClient: ApiClient): Promise<CongressMemberSummary[]> {
  return apiClient.requestJson<CongressMemberSummary[]>(buildCongressMembersPath());
}

export async function fetchCongressMoneySummaries(apiClient: ApiClient): Promise<CongressMemberMoneySummary[]> {
  return apiClient.requestJson<CongressMemberMoneySummary[]>(buildCongressMoneySummariesPath());
}

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

export async function fetchElectionDateAggregate(
  apiClient: ApiClient,
  request: ElectionDateAggregateRequest
): Promise<ElectionDateAggregateResponse> {
  return apiClient.requestJson<ElectionDateAggregateResponse>(buildElectionDateAggregatePath(request.date));
}

export async function fetchUpcomingElectionTimeline(
  apiClient: ApiClient
): Promise<UpcomingElectionTimelineEntry[]> {
  return apiClient.requestJson<UpcomingElectionTimelineEntry[]>(buildUpcomingElectionTimelinePath());
}
