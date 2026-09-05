import {
  fetchPersonCandidateFinanceSections,
  fetchPersonContributionInsights,
  fetchPersonTopDonors,
  fetchPersonTopEmployers,
  type PersonCandidateFinanceSection
} from "./campaign-finance-detail";
import type { PersonContributionInsights } from "$lib/campaign-finance-detail/contract";
import {
  buildPersonMoneyAtGlanceSummary,
  type PersonMoneyAtGlanceSummary,
  PERSON_MISSING_SUMMARY_MESSAGE,
  PERSON_NO_LINKED_CANDIDACY_MESSAGE,
  PERSON_NOT_LOADED_MESSAGE,
  PERSON_TEMPORARILY_UNAVAILABLE_MESSAGE
} from "$lib/entity-detail/person-campaign-finance-presentation";
import type { ApiClient } from "./client";
import { ApiResponseError } from "./client";
import type { PersonDetailPageExtensions, PersonMoneyHeadlineState } from "./entity-detail";

type ContributionInsightsOutcome =
  | { kind: "loaded"; insights: PersonContributionInsights }
  | { kind: "unavailable"; error: unknown };

type LoadPersonMoneyBundleOptions = {
  fallbackWhenBackendSelectedInsightsUnavailable?: boolean;
};

function guardUnhandledRejection(promise: Promise<unknown>): void {
  void promise.catch(() => {});
}

function guardIfPromise(value: unknown): void {
  if (value instanceof Promise) {
    guardUnhandledRejection(value);
  }
}

function guardMoneyBundle(bundle: PersonDetailPageExtensions): PersonDetailPageExtensions {
  guardIfPromise(bundle.personMoneyHeadline);
  guardUnhandledRejection(bundle.personFinanceSections);
  guardIfPromise(bundle.personContributionInsights);
  guardIfPromise(bundle.personTopDonors);
  guardIfPromise(bundle.personTopEmployers);
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

function buildMissingSummaryHeadline(selectedCycle?: number): PersonMoneyHeadlineState {
  const headline = {
    kind: "missing_summary",
    message: PERSON_MISSING_SUMMARY_MESSAGE
  } as const;
  return selectedCycle === undefined ? headline : { ...headline, selectedCycle };
}

function buildTemporarilyUnavailableHeadline(selectedCycle?: number): PersonMoneyHeadlineState {
  const headline = {
    kind: "temporarily_unavailable",
    message: PERSON_TEMPORARILY_UNAVAILABLE_MESSAGE
  } as const;
  return selectedCycle === undefined ? headline : { ...headline, selectedCycle };
}

function buildNotLoadedHeadline(
  selectedCycle: number,
  summary: PersonMoneyAtGlanceSummary
): PersonMoneyHeadlineState {
  return {
    kind: "not_loaded",
    message: PERSON_NOT_LOADED_MESSAGE,
    selectedCycle,
    // Passed through for the cycle switcher only. No figure from this summary
    // may be rendered in this arm; the values are placeholders for evidence
    // that was never loaded.
    summary
  };
}

async function resolvePersonMoneyHeadline(
  sections: PersonCandidateFinanceSection[],
  selectedCycle?: number
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
  const summary = buildPersonMoneyAtGlanceSummary(summaries);

  // A 200 is not evidence. `buildPersonMoneyAtGlanceSummary` already folds the
  // per-candidate discriminators into one aggregate `coverage.activity_state`
  // (populated wins, all-loaded_zero stays loaded_zero, otherwise not_loaded); this is
  // the only place that reads it for the headline. Without this branch a not-loaded
  // payload falls through as `loaded` and the metric grid publishes the backend's
  // placeholder "0.00" as "Total receipts $0.00".
  //
  // Deliberately narrow: only `not_loaded` diverts. `loaded_zero` is authoritative
  // proof of genuine no-money coverage and must keep rendering explicit zeroes.
  if (summary.coverage.activity_state === "not_loaded") {
    // Prefer the cycle the money payload itself reports over the caller's parameter,
    // so the rendered cycle label matches the cycle whose evidence is missing.
    return buildNotLoadedHeadline(summary.selected_cycle, summary);
  }

  return {
    kind: "loaded",
    summary
  };
}

async function resolvePersonMoneyHeadlineFromSections(
  sections: Promise<PersonCandidateFinanceSection[]>,
  selectedCycle?: number
): Promise<PersonMoneyHeadlineState> {
  try {
    return await resolvePersonMoneyHeadline(await sections, selectedCycle);
  } catch {
    return buildTemporarilyUnavailableHeadline(selectedCycle);
  }
}

function shouldSurfaceContributionInsightsError(error: unknown): boolean {
  return error instanceof ApiResponseError && (error.status === 400 || error.status === 422);
}

/**
 */
async function loadContributionInsightsOutcome(
  apiClient: ApiClient,
  personId: string,
  fallbackWhenUnavailable: boolean,
  selectedCycle?: number
): Promise<ContributionInsightsOutcome> {
  try {
    const insights = await fetchPersonContributionInsights(apiClient, {
      id: personId,
      cycle: selectedCycle
    });
    return { kind: "loaded", insights };
  } catch (error) {
    if (!fallbackWhenUnavailable || shouldSurfaceContributionInsightsError(error)) {
      throw error;
    }
    return {
      kind: "unavailable",
      error
    };
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
  const personContributionInsights = contributionInsightsOutcome.then((outcome) => {
    if (outcome.kind === "unavailable") {
      throw outcome.error;
    }
    return outcome.insights;
  });

  function loadAfterContributionInsights<T>(
    load: (cycle?: number) => Promise<T>
  ): Promise<T> {
    return contributionInsightsOutcome.then((outcome) => {
      if (outcome.kind === "unavailable") {
        return load();
      }
      return load(outcome.insights.metadata.selected_cycle);
    });
  }

  const personFinanceSections = loadAfterContributionInsights<PersonCandidateFinanceSection[]>(
    (cycle) => fetchPersonCandidateFinanceSections(apiClient, { personId, cycle })
  );

  return guardMoneyBundle({
    personContributionInsights,
    personMoneyHeadline: contributionInsightsOutcome.then(async (outcome) => {
      return resolvePersonMoneyHeadlineFromSections(
        personFinanceSections,
        outcome.kind === "loaded" ? outcome.insights.metadata.selected_cycle : undefined
      );
    }),
    personFinanceSections,
    personTopDonors: loadAfterContributionInsights((cycle) =>
      fetchPersonTopDonors(apiClient, { id: personId, cycle })
    ),
    personTopEmployers: loadAfterContributionInsights((cycle) =>
      fetchPersonTopEmployers(apiClient, { id: personId, cycle })
    )
  });
}

async function loadExplicitCycleMoney(
  apiClient: ApiClient,
  personId: string,
  cycle: number
): Promise<PersonDetailPageExtensions> {
  const personFinanceSections = fetchPersonCandidateFinanceSections(apiClient, { personId, cycle });
  const contributionInsightsOutcome = loadContributionInsightsOutcome(apiClient, personId, true, cycle);
  const personContributionInsights = contributionInsightsOutcome.then((outcome) => {
    if (outcome.kind === "unavailable") {
      throw outcome.error;
    }
    return outcome.insights;
  });
  const bundle = guardMoneyBundle({
    personMoneyHeadline: resolvePersonMoneyHeadlineFromSections(personFinanceSections, cycle),
    personFinanceSections,
    personContributionInsights,
    personTopDonors: fetchPersonTopDonors(apiClient, { id: personId, cycle }),
    personTopEmployers: fetchPersonTopEmployers(apiClient, { id: personId, cycle })
  });

  await contributionInsightsOutcome;
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
