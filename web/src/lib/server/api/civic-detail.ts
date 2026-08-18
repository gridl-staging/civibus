import {
  buildCongressMembersPath,
  buildCongressMoneySummariesPath,
  buildElectionDateAggregatePath,
  buildUpcomingElectionTimelinePath,
  buildCandidacyDetailPath,
  buildContestCandidateMoneyPath,
  buildContestDetailPath,
  buildOfficeDetailPath,
  buildOfficeholdingDetailPath,
  type CongressMemberSummary,
  type CongressMemberMoneySummary,
  type CandidacyDetailResponse,
  type ContestCandidateMoneyResponse,
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

export type ContestCandidateMoneyRequest = {
  id: string;
  cycle?: number;
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

/**
 * Fetch the whole race money scoreboard in one backend call.
 *
 * Deliberately NOT wrapped in a try/catch. The previous per-candidacy
 * implementation swallowed every failure into an empty section, so a backend
 * outage rendered as "data is not yet available" and was indistinguishable
 * from a real data gap. Letting this reject lets the route's error handling
 * surface a real failure as a real failure.
 */
export async function fetchContestCandidateMoney(
  apiClient: ApiClient,
  request: ContestCandidateMoneyRequest
): Promise<ContestCandidateMoneyResponse> {
  return apiClient.requestJson<ContestCandidateMoneyResponse>(
    buildContestCandidateMoneyPath(request.id, { cycle: request.cycle })
  );
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
