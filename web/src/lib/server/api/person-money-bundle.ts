import {
  fetchPersonCandidateFinanceSections,
  fetchPersonContributionInsights,
  fetchPersonTopDonors,
  fetchPersonTopEmployers
} from "./campaign-finance-detail";
import type { ApiClient } from "./client";
import type { PersonDetailPageExtensions } from "./entity-detail";

function guardUnhandledRejection(promise: Promise<unknown>): void {
  void promise.catch(() => {});
}

function guardMoneyBundle(bundle: PersonDetailPageExtensions): PersonDetailPageExtensions {
  guardUnhandledRejection(bundle.personFinanceSections);
  guardUnhandledRejection(bundle.personContributionInsights);
  guardUnhandledRejection(bundle.personTopDonors);
  guardUnhandledRejection(bundle.personTopEmployers);
  return bundle;
}

/**
 */
function loadBackendSelectedCycleMoney(
  apiClient: ApiClient,
  personId: string
): PersonDetailPageExtensions {
  const personContributionInsights = fetchPersonContributionInsights(apiClient, {
    id: personId
  });
  const selectedCycle = personContributionInsights.then(
    (contributionInsights) => contributionInsights.metadata.selected_cycle
  );

  return guardMoneyBundle({
    personContributionInsights,
    personFinanceSections: selectedCycle.then((cycle) =>
      fetchPersonCandidateFinanceSections(apiClient, { personId, cycle })
    ),
    personTopDonors: selectedCycle.then((cycle) =>
      fetchPersonTopDonors(apiClient, { id: personId, cycle })
    ),
    personTopEmployers: selectedCycle.then((cycle) =>
      fetchPersonTopEmployers(apiClient, { id: personId, cycle })
    )
  });
}

async function loadExplicitCycleMoney(
  apiClient: ApiClient,
  personId: string,
  cycle: number
): Promise<PersonDetailPageExtensions> {
  const bundle = guardMoneyBundle({
    personFinanceSections: fetchPersonCandidateFinanceSections(apiClient, { personId, cycle }),
    personContributionInsights: fetchPersonContributionInsights(apiClient, { id: personId, cycle }),
    personTopDonors: fetchPersonTopDonors(apiClient, { id: personId, cycle }),
    personTopEmployers: fetchPersonTopEmployers(apiClient, { id: personId, cycle })
  });

  await bundle.personContributionInsights;
  return bundle;
}

/** Loads the four person-money streams under one selected-cycle contract. */
export function loadPersonMoneyBundle(
  apiClient: ApiClient,
  personId: string
): PersonDetailPageExtensions;
export function loadPersonMoneyBundle(
  apiClient: ApiClient,
  personId: string,
  cycle: number
): Promise<PersonDetailPageExtensions>;
export function loadPersonMoneyBundle(
  apiClient: ApiClient,
  personId: string,
  cycle?: number
): PersonDetailPageExtensions | Promise<PersonDetailPageExtensions> {
  if (cycle === undefined) {
    return loadBackendSelectedCycleMoney(apiClient, personId);
  }

  return loadExplicitCycleMoney(apiClient, personId, cycle);
}
