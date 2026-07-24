import type {
  CandidateFundraisingSummary,
  CandidateMoneyActivityState,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary
} from "$lib/campaign-finance-detail/contract";
import {
  buildCandidateDeferredCommitteeBreakdown,
  buildCandidateDeferredFundraisingSummary,
  buildCandidateDeferredKeyMetrics,
  buildOutsideSpendingPresentation,
  CANDIDATE_IE_NOT_LOADED_MESSAGE,
  CANDIDATE_METHODOLOGY_HREF,
  selectOutsideSpendingSummaryForCycle,
  selectOutsideSpendingTransactionsForCycle,
  type CandidateAggregateSummaryPresentation,
  type CandidateCommitteeBreakdownRow,
  type KeyMetric,
  type OutsideSpendingPresentation
} from "$lib/campaign-finance-detail/presentation";

type CandidateMoneyRegionState = CandidateMoneyActivityState | "backend_failure";

export type CandidateFundraisingRegionViewModels = {
  keyFinancials: {
    state: CandidateMoneyRegionState;
    message: string | null;
    methodologyHref: string | null;
    metrics: KeyMetric[];
  };
  fundraisingSummary: {
    state: CandidateMoneyRegionState;
    message: string | null;
    methodologyHref: string | null;
    summary: CandidateAggregateSummaryPresentation | null;
  };
  committeeBreakdown: {
    state: CandidateMoneyRegionState;
    message: string | null;
    methodologyHref: string | null;
    rows: CandidateCommitteeBreakdownRow[];
  };
};

export type CandidateOutsideSpendingRegionViewModel = {
  state: CandidateMoneyRegionState;
  message: string | null;
  methodologyHref: string | null;
  presentation: OutsideSpendingPresentation | null;
};

const KEY_FINANCIALS_NOT_LOADED_MESSAGE =
  "Campaign-finance totals are not yet available for this candidate and cycle.";
const KEY_FINANCIALS_LOADED_ZERO_MESSAGE =
  "No fundraising activity is reported in loaded filings for this candidate and cycle.";
const KEY_FINANCIALS_BACKEND_FAILURE_MESSAGE =
  "Candidate financial totals are temporarily unavailable.";
const FUNDRAISING_NOT_LOADED_MESSAGE =
  "Fundraising data is not yet available for this candidate and cycle.";
const FUNDRAISING_BACKEND_FAILURE_MESSAGE =
  "Candidate fundraising summary is temporarily unavailable.";
const COMMITTEE_BREAKDOWN_NOT_LOADED_MESSAGE =
  "Committee breakdown is not yet available for this candidate and cycle.";
const COMMITTEE_BREAKDOWN_LOADED_ZERO_MESSAGE =
  "No authorized committee activity is reported in loaded filings for this candidate and cycle.";
const COMMITTEE_BREAKDOWN_BACKEND_FAILURE_MESSAGE =
  "Committee breakdown is temporarily unavailable.";
const IE_LOADED_ZERO_MESSAGE =
  "No FEC Schedule E independent expenditures are reported in loaded filings for this candidate and cycle.";
const IE_BACKEND_FAILURE_MESSAGE = "Outside-spending data is temporarily unavailable.";

function buildUnavailableFundraisingRegions(
  state: "backend_failure" | "not_loaded"
): CandidateFundraisingRegionViewModels {
  const isNotLoaded = state === "not_loaded";
  const methodologyHref = isNotLoaded ? CANDIDATE_METHODOLOGY_HREF : null;
  return {
    keyFinancials: {
      state,
      message: isNotLoaded
        ? KEY_FINANCIALS_NOT_LOADED_MESSAGE
        : KEY_FINANCIALS_BACKEND_FAILURE_MESSAGE,
      methodologyHref,
      metrics: []
    },
    fundraisingSummary: {
      state,
      message: isNotLoaded ? FUNDRAISING_NOT_LOADED_MESSAGE : FUNDRAISING_BACKEND_FAILURE_MESSAGE,
      methodologyHref,
      summary: null
    },
    committeeBreakdown: {
      state,
      message: isNotLoaded
        ? COMMITTEE_BREAKDOWN_NOT_LOADED_MESSAGE
        : COMMITTEE_BREAKDOWN_BACKEND_FAILURE_MESSAGE,
      methodologyHref,
      rows: []
    }
  };
}

export function buildCandidateFundraisingRegionViewModels(
  summary: CandidateFundraisingSummary | null
): CandidateFundraisingRegionViewModels {
  if (summary === null) {
    return buildUnavailableFundraisingRegions("backend_failure");
  }
  if (summary.coverage.activity_state === "not_loaded") {
    return buildUnavailableFundraisingRegions("not_loaded");
  }

  const state = summary.coverage.activity_state;
  const loadedZeroMessage = state === "loaded_zero" ? KEY_FINANCIALS_LOADED_ZERO_MESSAGE : null;
  return {
    keyFinancials: {
      state,
      message: loadedZeroMessage,
      methodologyHref: null,
      metrics: buildCandidateDeferredKeyMetrics(summary)
    },
    fundraisingSummary: {
      state,
      message: loadedZeroMessage,
      methodologyHref: null,
      summary: buildCandidateDeferredFundraisingSummary(summary)
    },
    committeeBreakdown: {
      state,
      message: state === "loaded_zero" ? COMMITTEE_BREAKDOWN_LOADED_ZERO_MESSAGE : null,
      methodologyHref: null,
      rows: buildCandidateDeferredCommitteeBreakdown(summary)
    }
  };
}

export function buildCandidateOutsideSpendingRegionViewModel(
  ieSummary: IndependentExpenditureSummary | null,
  ieTransactions: IndependentExpenditureResponse[],
  selectedCycleOverride: number | null = null
): CandidateOutsideSpendingRegionViewModel {
  const selectedSummary = selectOutsideSpendingSummaryForCycle(ieSummary, selectedCycleOverride);
  if (selectedSummary === null) {
    return {
      state: "backend_failure",
      message: IE_BACKEND_FAILURE_MESSAGE,
      methodologyHref: null,
      presentation: null
    };
  }
  if (selectedSummary.coverage.activity_state === "not_loaded") {
    return {
      state: "not_loaded",
      message: CANDIDATE_IE_NOT_LOADED_MESSAGE,
      methodologyHref: CANDIDATE_METHODOLOGY_HREF,
      presentation: null
    };
  }

  const selectedTransactions = selectOutsideSpendingTransactionsForCycle(
    ieSummary,
    ieTransactions,
    selectedCycleOverride
  );
  return {
    state: selectedSummary.coverage.activity_state,
    message:
      selectedSummary.coverage.activity_state === "loaded_zero" ? IE_LOADED_ZERO_MESSAGE : null,
    methodologyHref: null,
    presentation: buildOutsideSpendingPresentation(selectedSummary, selectedTransactions)
  };
}
