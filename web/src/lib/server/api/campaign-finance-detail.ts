/** Fetch helpers for campaign-finance detail routes, lists, and slug lookups. */
import {
  buildCandidateDetailPath,
  buildCandidateHref,
  buildCandidateIndependentExpendituresPath,
  buildCandidateIndependentExpendituresSummaryPath,
  buildCandidateListPath,
  buildCandidateSummaryPath,
  buildCandidatesBySlugPath,
  buildCountyCampaignFinanceSummaryPath,
  buildCommitteeDetailPath,
  buildCommitteeFilingBreakdownPath,
  buildCommitteeIndependentExpendituresMadePath,
  buildCommitteeListPath,
  buildCommitteeSummaryPath,
  buildCommitteeTransactionsPath,
  buildCommitteesBySlugPath,
  buildPersonContributionInsightsPath,
  buildPersonTopDonorsPath,
  buildPersonTopEmployersPath,
  type CandidateDetailResponse,
  type CandidateFundraisingSummary,
  type CandidateListRequest as CandidateListPathRequest,
  type CandidateListResponse,
  type CandidateSlugMatchResponse,
  type CampaignFinanceTransactionResponse,
  type CountyCampaignFinanceSummaryResponse,
  type CommitteeDetailResponse,
  type CommitteeFilingBreakdown,
  type CommitteeFundraisingSummary,
  type CommitteeIndependentExpenditureActivity,
  type CommitteeListRequest as CommitteeListPathRequest,
  type CommitteeListResponse,
  type CommitteeSlugMatchResponse,
  type IndependentExpenditureResponse,
  type IndependentExpenditureSummary,
  type PersonContributionInsights,
  type PersonTopEmployerRow,
  type RankedTransactionParty,
  type SelectedCycleRequest
} from "$lib/campaign-finance-detail/contract";
import { ApiResponseError, type ApiClient } from "./client";

type IdRequest = { id: string };
type CycleScopedIdRequest = IdRequest & SelectedCycleRequest;
type SlugRequest = { slug: string };

export type CommitteeDetailRequest = CycleScopedIdRequest;
export type CandidateDetailRequest = CycleScopedIdRequest;
export type CandidateListRequest = CandidateListPathRequest;
export type CommitteeListRequest = CommitteeListPathRequest;
export type CandidateBySlugRequest = SlugRequest;
export type CommitteeBySlugRequest = SlugRequest;
export type CountyCampaignFinanceSummaryRequest = {
  state: string;
  countySlug: string;
};

export type CommitteeDetailBundle = {
  detail: CommitteeDetailResponse;
  transactions: Promise<CampaignFinanceTransactionResponse[]>;
  summary: Promise<CommitteeFundraisingSummary>;
  filingBreakdown: CommitteeFilingBreakdown;
  independentExpendituresMade: Promise<CommitteeIndependentExpenditureActivity>;
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

function fetchByCycleScopedId<TResponse>(
  apiClient: ApiClient,
  request: CycleScopedIdRequest,
  buildPath: (id: string, request: SelectedCycleRequest) => string
): Promise<TResponse> {
  return fetchByRequest(apiClient, request, ({ id, cycle }) => buildPath(id, { cycle }));
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
  return fetchByCycleScopedId(apiClient, request, buildCommitteeTransactionsPath);
}

export async function fetchCommitteeSummary(
  apiClient: ApiClient,
  request: CommitteeDetailRequest
): Promise<CommitteeFundraisingSummary> {
  return fetchByCycleScopedId(apiClient, request, buildCommitteeSummaryPath);
}

export async function fetchCommitteeFilingBreakdown(
  apiClient: ApiClient,
  request: CommitteeDetailRequest
): Promise<CommitteeFilingBreakdown> {
  return fetchById(apiClient, request, buildCommitteeFilingBreakdownPath);
}

export async function fetchCommitteeIndependentExpendituresMade(
  apiClient: ApiClient,
  request: CommitteeDetailRequest
): Promise<CommitteeIndependentExpenditureActivity> {
  return fetchById(apiClient, request, buildCommitteeIndependentExpendituresMadePath);
}

export type CandidateDetailBundle = {
  detail: CandidateDetailResponse;
  summary: Promise<CandidateFundraisingSummary>;
  ieTransactions: Promise<IndependentExpenditureResponse[]>;
  ieSummary: Promise<IndependentExpenditureSummary | null>;
};

export type PersonCandidateFinanceSection = {
  candidate: CandidateDetailResponse;
  summary: Promise<CandidateFundraisingSummary>;
  ieTransactions: Promise<IndependentExpenditureResponse[]>;
  ieSummary: IndependentExpenditureSummary | null;
  donorVendorTransactions: Promise<CampaignFinanceTransactionResponse[]>;
};

export type PersonCandidateFinanceRequest = {
  personId: string;
  limit?: number;
  cycle?: number;
};

export type ContestCandidacyFinanceRequestItem = {
  personId: string;
};

export type ContestCandidateFinanceSection = {
  personId: string;
  candidateHref: string | null;
  summary: CandidateFundraisingSummary | null;
  ieSummary: IndependentExpenditureSummary | null;
  ieTransactions: IndependentExpenditureResponse[];
};

export type ContestCandidateFinanceByPersonId = Record<string, ContestCandidateFinanceSection>;

export type ContestCandidateFinanceRequest = {
  candidacies: ContestCandidacyFinanceRequestItem[];
  limitPerPerson?: number;
  cycle?: number;
};

export async function fetchCandidateSummary(
  apiClient: ApiClient,
  request: CandidateDetailRequest
): Promise<CandidateFundraisingSummary> {
  return fetchByCycleScopedId(apiClient, request, buildCandidateSummaryPath);
}

export async function fetchCandidateIndependentExpenditures(
  apiClient: ApiClient,
  request: CandidateDetailRequest
): Promise<IndependentExpenditureResponse[]> {
  return fetchByCycleScopedId(apiClient, request, buildCandidateIndependentExpendituresPath);
}

export async function fetchCandidateIndependentExpendituresSummary(
  apiClient: ApiClient,
  request: CandidateDetailRequest
): Promise<IndependentExpenditureSummary | null> {
  return fetchByCycleScopedId(apiClient, request, buildCandidateIndependentExpendituresSummaryPath);
}

export async function fetchPersonContributionInsights(
  apiClient: ApiClient,
  request: CycleScopedIdRequest
): Promise<PersonContributionInsights> {
  return fetchByCycleScopedId(apiClient, request, buildPersonContributionInsightsPath);
}

export async function fetchPersonTopDonors(
  apiClient: ApiClient,
  request: CycleScopedIdRequest
): Promise<RankedTransactionParty[]> {
  return fetchByCycleScopedId(apiClient, request, buildPersonTopDonorsPath);
}

export async function fetchPersonTopEmployers(
  apiClient: ApiClient,
  request: CycleScopedIdRequest
): Promise<PersonTopEmployerRow[]> {
  return fetchByCycleScopedId(apiClient, request, buildPersonTopEmployersPath);
}

function guardUnhandledRejection(promise: Promise<unknown>): void {
  void promise.catch(() => {});
}

/**
 */
function collectLinkedCommitteeIds(
  summary: CandidateFundraisingSummary,
  principalCommitteeId: string | null
): string[] {
  const committeeIds: string[] = [];
  const seen = new Set<string>();

  if (principalCommitteeId !== null) {
    seen.add(principalCommitteeId);
    committeeIds.push(principalCommitteeId);
  }

  for (const committeeSummary of summary.committees) {
    if (seen.has(committeeSummary.committee_id)) {
      continue;
    }
    seen.add(committeeSummary.committee_id);
    committeeIds.push(committeeSummary.committee_id);
  }

  return committeeIds;
}

function parseTransactionSortDate(transactionDate: string | null): number | null {
  if (transactionDate === null) {
    return null;
  }

  const parsed = Date.parse(transactionDate);
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Applies deterministic ordering across merged committee transaction feeds.
 * Newer rows render first; same-date rows use canonical transaction id tie-breakers.
 */
function sortMergedDonorVendorTransactions(
  transactions: CampaignFinanceTransactionResponse[]
): CampaignFinanceTransactionResponse[] {
  return [...transactions].sort((left, right) => {
    const leftDate = parseTransactionSortDate(left.transaction_date);
    const rightDate = parseTransactionSortDate(right.transaction_date);

    if (leftDate !== null && rightDate !== null && leftDate !== rightDate) {
      return rightDate - leftDate;
    }

    if (leftDate === null && rightDate !== null) {
      return 1;
    }

    if (leftDate !== null && rightDate === null) {
      return -1;
    }

    return left.id.localeCompare(right.id);
  });
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

/**
 * Loads person-linked candidate finance inputs while reusing existing candidate/committee owners.
 * Summary + IE remain streamed promises so person detail sections can render progressively.
 */
export async function fetchPersonCandidateFinanceSections(
  apiClient: ApiClient,
  request: PersonCandidateFinanceRequest
): Promise<PersonCandidateFinanceSection[]> {
  const linkedCandidates = await fetchCandidateList(apiClient, {
    person_id: request.personId,
    limit: request.limit ?? 10,
    offset: 0
  });

  return Promise.all(
    linkedCandidates.items.map(async (candidateListItem) => {
      const candidateBundle = await fetchCandidateDetailBundle(apiClient, {
        id: candidateListItem.id,
        cycle: request.cycle
      });

      const donorVendorTransactions = candidateBundle.summary.then(async (summary) => {
        const committeeIds = collectLinkedCommitteeIds(
          summary,
          candidateBundle.detail.principal_committee_id
        );
        if (committeeIds.length === 0) {
          return [];
        }

        const transactionsByCommittee = await Promise.all(
          committeeIds.map((committeeId) =>
            fetchCommitteeTransactions(apiClient, {
              id: committeeId,
              cycle: request.cycle
            })
          )
        );
        return sortMergedDonorVendorTransactions(transactionsByCommittee.flat());
      });
      guardUnhandledRejection(donorVendorTransactions);
      const ieSummary = await candidateBundle.ieSummary;

      return {
        candidate: candidateBundle.detail,
        summary: candidateBundle.summary,
        ieTransactions: candidateBundle.ieTransactions,
        ieSummary,
        donorVendorTransactions
      };
    })
  );
}

function createEmptyContestCandidateFinanceSection(personId: string): ContestCandidateFinanceSection {
  return {
    personId,
    candidateHref: null,
    summary: null,
    ieSummary: null,
    ieTransactions: []
  };
}

/**
 */
function selectPersonCandidateFinanceSection(
  sections: PersonCandidateFinanceSection[],
  personId: string
): PersonCandidateFinanceSection | null {
  if (sections.length === 0) {
    return null;
  }

  for (const section of sections) {
    if (section.candidate.person_id === personId) {
      return section;
    }
  }

  return sections[0];
}

/**
 */
export async function fetchContestCandidateFinanceByPersonId(
  apiClient: ApiClient,
  request: ContestCandidateFinanceRequest
): Promise<ContestCandidateFinanceByPersonId> {
  const personIds = [...new Set(request.candidacies.map((candidacy) => candidacy.personId))];
  const entries = await Promise.all(
    personIds.map(async (personId) => {
      try {
        const personSections = await fetchPersonCandidateFinanceSections(apiClient, {
          personId,
          limit: request.limitPerPerson ?? 10,
          cycle: request.cycle
        });
        const matchedSection = selectPersonCandidateFinanceSection(personSections, personId);
        if (matchedSection === null) {
          return [personId, createEmptyContestCandidateFinanceSection(personId)] as const;
        }

        const [summary, ieSummary, ieTransactions] = await Promise.all([
          matchedSection.summary,
          matchedSection.ieSummary,
          matchedSection.ieTransactions
        ]);
        return [
          personId,
          {
            personId,
            candidateHref: buildCandidateHref(matchedSection.candidate),
            summary,
            ieSummary,
            ieTransactions
          }
        ] as const;
      } catch {
        return [personId, createEmptyContestCandidateFinanceSection(personId)] as const;
      }
    })
  );

  return Object.fromEntries(entries);
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

export async function fetchCountyCampaignFinanceSummary(
  apiClient: ApiClient,
  request: CountyCampaignFinanceSummaryRequest
): Promise<CountyCampaignFinanceSummaryResponse> {
  return fetchByRequest(apiClient, request, ({ state, countySlug }) =>
    buildCountyCampaignFinanceSummaryPath(state, countySlug)
  );
}

/** Loads the candidate detail shell; secondary fields stream as unresolved promises. */
export async function fetchCandidateDetailBundle(
  apiClient: ApiClient,
  request: CandidateDetailRequest
): Promise<CandidateDetailBundle> {
  const detailPromise = fetchCandidateDetail(apiClient, request);
  const summaryPromise = fetchCandidateSummary(apiClient, request);
  const ieTransactionsPromise = fetchOptionalCandidateData(
    () => fetchCandidateIndependentExpenditures(apiClient, request),
    []
  );
  const ieSummaryPromise = fetchOptionalCandidateData(
    () => fetchCandidateIndependentExpendituresSummary(apiClient, request),
    null
  );
  guardUnhandledRejection(summaryPromise);
  guardUnhandledRejection(ieTransactionsPromise);
  guardUnhandledRejection(ieSummaryPromise);

  try {
    const detail = await detailPromise;
    return {
      detail,
      summary: summaryPromise,
      ieTransactions: ieTransactionsPromise,
      ieSummary: ieSummaryPromise
    };
  } catch (error) {
    void Promise.allSettled([summaryPromise, ieTransactionsPromise, ieSummaryPromise]);
    throw error;
  }
}

/** Loads the committee detail shell; filing breakdown is SSR-visible for curl evidence. */
export async function fetchCommitteeDetailBundle(
  apiClient: ApiClient,
  request: CommitteeDetailRequest
): Promise<CommitteeDetailBundle> {
  const detailPromise = fetchCommitteeDetail(apiClient, request);
  const transactionsPromise = fetchCommitteeTransactions(apiClient, request);
  const summaryPromise = fetchCommitteeSummary(apiClient, request);
  const filingBreakdownPromise = fetchCommitteeFilingBreakdown(apiClient, request);
  const independentExpendituresMadePromise = fetchCommitteeIndependentExpendituresMade(apiClient, request);
  guardUnhandledRejection(transactionsPromise);
  guardUnhandledRejection(summaryPromise);
  guardUnhandledRejection(filingBreakdownPromise);
  guardUnhandledRejection(independentExpendituresMadePromise);

  try {
    const [detail, filingBreakdown] = await Promise.all([detailPromise, filingBreakdownPromise]);
    return {
      detail,
      transactions: transactionsPromise,
      summary: summaryPromise,
      filingBreakdown,
      independentExpendituresMade: independentExpendituresMadePromise
    };
  } catch (error) {
    void Promise.allSettled([
      transactionsPromise,
      summaryPromise,
      filingBreakdownPromise,
      independentExpendituresMadePromise
    ]);
    throw error;
  }
}
