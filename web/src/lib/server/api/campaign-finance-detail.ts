/** Fetch helpers for campaign-finance detail routes, lists, and slug lookups. */
import {
  buildCandidateDetailPath,
  buildCandidateIndependentExpendituresPath,
  buildCandidateIndependentExpendituresSummaryPath,
  buildCandidateListPath,
  buildCandidateSummaryPath,
  buildCandidatesBySlugPath,
  buildCommitteeDetailPath,
  buildCommitteeFilingBreakdownPath,
  buildCommitteeListPath,
  buildCommitteeSummaryPath,
  buildCommitteeTransactionsPath,
  buildCommitteesBySlugPath,
  type CandidateDetailResponse,
  type CandidateFundraisingSummary,
  type CandidateListRequest as CandidateListPathRequest,
  type CandidateListResponse,
  type CandidateSlugMatchResponse,
  type CampaignFinanceTransactionResponse,
  type CommitteeDetailResponse,
  type CommitteeFilingBreakdown,
  type CommitteeFundraisingSummary,
  type CommitteeListRequest as CommitteeListPathRequest,
  type CommitteeListResponse,
  type CommitteeSlugMatchResponse,
  type IndependentExpenditureResponse,
  type IndependentExpenditureSummary
} from "$lib/campaign-finance-detail/contract";
import { ApiResponseError, type ApiClient } from "./client";

type IdRequest = { id: string };
type SlugRequest = { slug: string };

export type CommitteeDetailRequest = IdRequest;
export type CandidateDetailRequest = IdRequest;
export type CandidateListRequest = CandidateListPathRequest;
export type CommitteeListRequest = CommitteeListPathRequest;
export type CandidateBySlugRequest = SlugRequest;
export type CommitteeBySlugRequest = SlugRequest;

export type CommitteeDetailBundle = {
  detail: CommitteeDetailResponse;
  transactions: CampaignFinanceTransactionResponse[];
  summary: CommitteeFundraisingSummary;
  filingBreakdown: CommitteeFilingBreakdown;
};

function fetchByRequest<TResponse, TRequest>(
  apiClient: ApiClient,
  request: TRequest,
  buildPath: (request: TRequest) => string
): Promise<TResponse> {
  return apiClient.requestJson<TResponse>(buildPath(request));
}

function fetchById<TResponse>(
  apiClient: ApiClient,
  request: IdRequest,
  buildPath: (id: string) => string
): Promise<TResponse> {
  return fetchByRequest(apiClient, request, ({ id }) => buildPath(id));
}

export async function fetchCommitteeDetail(
  apiClient: ApiClient,
  request: CommitteeDetailRequest
): Promise<CommitteeDetailResponse> {
  return fetchById(apiClient, request, buildCommitteeDetailPath);
}

export async function fetchCandidateDetail(
  apiClient: ApiClient,
  request: CandidateDetailRequest
): Promise<CandidateDetailResponse> {
  return fetchById(apiClient, request, buildCandidateDetailPath);
}

export async function fetchCommitteeTransactions(
  apiClient: ApiClient,
  request: CommitteeDetailRequest
): Promise<CampaignFinanceTransactionResponse[]> {
  return fetchById(apiClient, request, buildCommitteeTransactionsPath);
}

export async function fetchCommitteeSummary(
  apiClient: ApiClient,
  request: CommitteeDetailRequest
): Promise<CommitteeFundraisingSummary> {
  return fetchById(apiClient, request, buildCommitteeSummaryPath);
}

export async function fetchCommitteeFilingBreakdown(
  apiClient: ApiClient,
  request: CommitteeDetailRequest
): Promise<CommitteeFilingBreakdown> {
  return fetchById(apiClient, request, buildCommitteeFilingBreakdownPath);
}

export type CandidateDetailBundle = {
  detail: CandidateDetailResponse;
  summary: CandidateFundraisingSummary;
  ieTransactions: IndependentExpenditureResponse[];
  ieSummary: IndependentExpenditureSummary | null;
};

export async function fetchCandidateSummary(
  apiClient: ApiClient,
  request: CandidateDetailRequest
): Promise<CandidateFundraisingSummary> {
  return fetchById(apiClient, request, buildCandidateSummaryPath);
}

export async function fetchCandidateIndependentExpenditures(
  apiClient: ApiClient,
  request: CandidateDetailRequest
): Promise<IndependentExpenditureResponse[]> {
  return fetchById(apiClient, request, buildCandidateIndependentExpendituresPath);
}

export async function fetchCandidateIndependentExpendituresSummary(
  apiClient: ApiClient,
  request: CandidateDetailRequest
): Promise<IndependentExpenditureSummary | null> {
  return fetchById(apiClient, request, buildCandidateIndependentExpendituresSummaryPath);
}

async function fetchOptionalCandidateData<T>(operation: () => Promise<T>, fallbackValue: T): Promise<T> {
  try {
    return await operation();
  } catch (cause) {
    if (cause instanceof ApiResponseError && cause.status === 404) {
      return fallbackValue;
    }

    throw cause;
  }
}

export async function fetchCandidateList(
  apiClient: ApiClient,
  request: CandidateListRequest
): Promise<CandidateListResponse> {
  return fetchByRequest(apiClient, request, buildCandidateListPath);
}

export async function fetchCommitteeList(
  apiClient: ApiClient,
  request: CommitteeListRequest
): Promise<CommitteeListResponse> {
  return fetchByRequest(apiClient, request, buildCommitteeListPath);
}

export async function fetchCandidatesBySlug(
  apiClient: ApiClient,
  request: CandidateBySlugRequest
): Promise<CandidateSlugMatchResponse> {
  return fetchByRequest(apiClient, request, ({ slug }) => buildCandidatesBySlugPath(slug));
}

export async function fetchCommitteesBySlug(
  apiClient: ApiClient,
  request: CommitteeBySlugRequest
): Promise<CommitteeSlugMatchResponse> {
  return fetchByRequest(apiClient, request, ({ slug }) => buildCommitteesBySlugPath(slug));
}

/** Loads the candidate detail bundle and tolerates missing IE endpoints as empty state. */
export async function fetchCandidateDetailBundle(
  apiClient: ApiClient,
  request: CandidateDetailRequest
): Promise<CandidateDetailBundle> {
  const [detail, summary, ieTransactions, ieSummary] = await Promise.all([
    fetchCandidateDetail(apiClient, request),
    fetchCandidateSummary(apiClient, request),
    fetchOptionalCandidateData(
      () => fetchCandidateIndependentExpenditures(apiClient, request),
      []
    ),
    fetchOptionalCandidateData(
      () => fetchCandidateIndependentExpendituresSummary(apiClient, request),
      null
    )
  ]);

  return { detail, summary, ieTransactions, ieSummary };
}

export async function fetchCommitteeDetailBundle(
  apiClient: ApiClient,
  request: CommitteeDetailRequest
): Promise<CommitteeDetailBundle> {
  const [detail, transactions, summary, filingBreakdown] = await Promise.all([
    fetchCommitteeDetail(apiClient, request),
    fetchCommitteeTransactions(apiClient, request),
    fetchCommitteeSummary(apiClient, request),
    fetchCommitteeFilingBreakdown(apiClient, request)
  ]);

  return { detail, transactions, summary, filingBreakdown };
}
