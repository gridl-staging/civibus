import {
  fetchPersonCandidateFinanceSections,
  fetchPersonContributionInsights,
  fetchPersonTopDonors,
  fetchPersonTopEmployers,
  type PersonCandidateFinanceSection
} from "./campaign-finance-detail";
import type { CandidateFundraisingSummary, PersonContributionInsights } from "$lib/campaign-finance-detail/contract";
import {
  buildPersonMoneyAtGlanceSummary,
  PERSON_MISSING_SUMMARY_MESSAGE,
  PERSON_NO_LINKED_CANDIDACY_MESSAGE,
  PERSON_TEMPORARILY_UNAVAILABLE_MESSAGE
} from "$lib/entity-detail/person-campaign-finance-presentation";
import type { ApiClient } from "./client";
import { ApiResponseError } from "./client";
import type { PersonDetailPageExtensions, PersonMoneyHeadlineState } from "./entity-detail";

type ContributionInsightsOutcome =
  | { kind: "loaded"; insights: PersonContributionInsights }
  | { kind: "unavailable"; insights: PersonContributionInsights };

type LoadPersonMoneyBundleOptions = {
  fallbackWhenBackendSelectedInsightsUnavailable?: boolean;
};

const DEFAULT_BACKEND_SELECTED_CYCLE = 2026;

function guardUnhandledRejection(promise: Promise<unknown>): void {
  void promise.catch(() => {});
}

function guardMoneyBundle(bundle: PersonDetailPageExtensions): PersonDetailPageExtensions {
  if (bundle.personMoneyHeadline instanceof Promise) {
    guardUnhandledRejection(bundle.personMoneyHeadline);
  }
  guardUnhandledRejection(bundle.personFinanceSections);
  guardUnhandledRejection(bundle.personContributionInsights);
  guardUnhandledRejection(bundle.personTopDonors);
  guardUnhandledRejection(bundle.personTopEmployers);
  return bundle;
}

function isMissingSummaryError(cause: unknown): boolean {
  return cause instanceof ApiResponseError && cause.status === 404;
}

function fulfilledOutcome<T>(
  outcome: PromiseSettledResult<T>
): outcome is PromiseFulfilledResult<T> {
  return outcome.status === "fulfilled";
}

function buildMissingSummaryHeadline(selectedCycle: number): PersonMoneyHeadlineState {
  return {
    kind: "missing_summary",
    message: PERSON_MISSING_SUMMARY_MESSAGE,
    selectedCycle
  };
}

function buildTemporarilyUnavailableHeadline(selectedCycle: number): PersonMoneyHeadlineState {
  return {
    kind: "temporarily_unavailable",
    message: PERSON_TEMPORARILY_UNAVAILABLE_MESSAGE,
    selectedCycle
  };
}

async function resolvePersonMoneyHeadline(
  sections: PersonCandidateFinanceSection[],
  selectedCycle: number
): Promise<PersonMoneyHeadlineState> {
  if (sections.length === 0) {
    return {
      kind: "no_linked_candidate",
      message: PERSON_NO_LINKED_CANDIDACY_MESSAGE
    };
  }

  const summaryResults = await Promise.allSettled(sections.map((section) => section.summary));
  const rejectedSummaries = summaryResults.filter(
    (result): result is PromiseRejectedResult => result.status === "rejected"
  );
  if (rejectedSummaries.some((result) => !isMissingSummaryError(result.reason))) {
    return buildTemporarilyUnavailableHeadline(selectedCycle);
  }
  if (rejectedSummaries.length > 0) {
    return buildMissingSummaryHeadline(selectedCycle);
  }

  const summaries = summaryResults.filter(fulfilledOutcome).map((result) => result.value);
  return {
    kind: "loaded",
    summary: buildPersonMoneyAtGlanceSummary(summaries)
  };
}

async function resolvePersonMoneyHeadlineFromSections(
  sections: Promise<PersonCandidateFinanceSection[]>,
  selectedCycle: number
): Promise<PersonMoneyHeadlineState> {
  try {
    return await resolvePersonMoneyHeadline(await sections, selectedCycle);
  } catch {
    return buildTemporarilyUnavailableHeadline(selectedCycle);
  }
}

/**
 */
function buildUnavailableContributionInsights(
  personId: string,
  selectedCycle = DEFAULT_BACKEND_SELECTED_CYCLE
): PersonContributionInsights {
  return {
    person_id: personId,
    has_data: false,
    metadata: {
      selected_cycle: selectedCycle,
      coverage_start_date: `${selectedCycle - 1}-01-01`,
      coverage_end_date: `${selectedCycle}-12-31`,
      available_cycles: [selectedCycle],
      cycles_included: [],
      committee_count: 0,
      approximate_geography: false,
      excluded_geography: null,
      caveats: ["temporarily_unavailable"]
    },
    monthly_totals: [],
    itemized_size_buckets: [],
    dollars_by_size: [],
    cycle_totals: [],
    career_totals: {
      itemized_individual_contribution_amount: "0.00",
      itemized_transaction_count: 0,
      unitemized_individual_contribution_amount: "0.00",
      total_individual_contribution_amount: "0.00",
      source: "none"
    },
    geography: {
      by_state: [],
      by_district: [],
      district_share: {
        in_district_amount: null,
        out_of_district_amount: null,
        unknown_district_amount: null,
        share: null,
        available: false
      },
      geography_mode: "excluded",
      classified_amount: "0.00",
      classified_transaction_count: 0,
      unknown_amount: "0.00",
      unknown_transaction_count: 0
    },
    small_dollar_share: {
      small_dollar_amount: null,
      total_contribution_amount: null,
      share: null,
      available: false
    }
  };
}

/**
 */
async function loadContributionInsightsOutcome(
  apiClient: ApiClient,
  personId: string,
  fallbackWhenUnavailable: boolean
): Promise<ContributionInsightsOutcome> {
  try {
    const insights = await fetchPersonContributionInsights(apiClient, {
      id: personId
    });
    return { kind: "loaded", insights };
  } catch (error) {
    if (!fallbackWhenUnavailable) {
      throw error;
    }
    return { kind: "unavailable", insights: buildUnavailableContributionInsights(personId) };
  }
}

/**
 */
function loadBackendSelectedCycleMoney(
  apiClient: ApiClient,
  personId: string,
  options: LoadPersonMoneyBundleOptions = {}
): PersonDetailPageExtensions {
  const contributionInsightsOutcome = loadContributionInsightsOutcome(
    apiClient,
    personId,
    options.fallbackWhenBackendSelectedInsightsUnavailable === true
  );
  const personContributionInsights = contributionInsightsOutcome.then((outcome) => outcome.insights);

  function loadAfterContributionInsights<T>(
    load: (cycle: number) => Promise<T>,
    fallbackValue: T
  ): Promise<T> {
    return contributionInsightsOutcome.then((outcome) => {
      if (outcome.kind === "unavailable") {
        return fallbackValue;
      }
      return load(outcome.insights.metadata.selected_cycle);
    });
  }

  const personFinanceSections = loadAfterContributionInsights<PersonCandidateFinanceSection[]>(
    (cycle) => fetchPersonCandidateFinanceSections(apiClient, { personId, cycle }),
    []
  );

  return guardMoneyBundle({
    personContributionInsights,
    personMoneyHeadline: contributionInsightsOutcome.then(async (outcome) => {
      if (outcome.kind === "unavailable") {
        return buildTemporarilyUnavailableHeadline(outcome.insights.metadata.selected_cycle);
      }
      return resolvePersonMoneyHeadlineFromSections(
        personFinanceSections,
        outcome.insights.metadata.selected_cycle
      );
    }),
    personFinanceSections,
    personTopDonors: loadAfterContributionInsights(
      (cycle) => fetchPersonTopDonors(apiClient, { id: personId, cycle }),
      []
    ),
    personTopEmployers: loadAfterContributionInsights(
      (cycle) => fetchPersonTopEmployers(apiClient, { id: personId, cycle }),
      []
    )
  });
}

async function loadExplicitCycleMoney(
  apiClient: ApiClient,
  personId: string,
  cycle: number
): Promise<PersonDetailPageExtensions> {
  const personFinanceSections = fetchPersonCandidateFinanceSections(apiClient, { personId, cycle });
  const bundle = guardMoneyBundle({
    personMoneyHeadline: resolvePersonMoneyHeadlineFromSections(personFinanceSections, cycle),
    personFinanceSections,
    personContributionInsights: fetchPersonContributionInsights(apiClient, { id: personId, cycle }),
    personTopDonors: fetchPersonTopDonors(apiClient, { id: personId, cycle }),
    personTopEmployers: fetchPersonTopEmployers(apiClient, { id: personId, cycle })
  });

  await bundle.personContributionInsights;
  await bundle.personMoneyHeadline;
  return bundle;
}

/** Loads the four person-money streams under one selected-cycle contract. */
export function loadPersonMoneyBundle(
  apiClient: ApiClient,
  personId: string,
  options?: LoadPersonMoneyBundleOptions
): PersonDetailPageExtensions;
export function loadPersonMoneyBundle(
  apiClient: ApiClient,
  personId: string,
  cycle: number
): Promise<PersonDetailPageExtensions>;
export function loadPersonMoneyBundle(
  apiClient: ApiClient,
  personId: string,
  cycleOrOptions?: number | LoadPersonMoneyBundleOptions
): PersonDetailPageExtensions | Promise<PersonDetailPageExtensions> {
  if (typeof cycleOrOptions !== "number") {
    return loadBackendSelectedCycleMoney(apiClient, personId, cycleOrOptions);
  }

  return loadExplicitCycleMoney(apiClient, personId, cycleOrOptions);
}
