import {
  fetchEntityDetailBundle
} from "$lib/server/api/entity-detail";
import {
  fetchPersonCandidateFinanceSections,
  fetchPersonContributionInsights,
  fetchPersonTopDonors,
  fetchPersonTopEmployers
} from "$lib/server/api/campaign-finance-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { error } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

const INVALID_CYCLE_ERROR = {
  message: "Invalid cycle query parameter.",
  detail: "The cycle query parameter must be a single four-digit election cycle."
};

function guardUnhandledRejection(promise: Promise<unknown>): void {
  void promise.catch(() => {});
}

/**
 */
function parseSelectedCycle(searchParams: URLSearchParams): number | undefined {
  const cycleValues = searchParams.getAll("cycle");
  if (cycleValues.length === 0) {
    return undefined;
  }

  if (cycleValues.length !== 1) {
    throw error(400, INVALID_CYCLE_ERROR);
  }

  const rawCycle = cycleValues[0].trim();
  if (!/^\d{4}$/.test(rawCycle)) {
    throw error(400, INVALID_CYCLE_ERROR);
  }

  return Number(rawCycle);
}

/**
 */
export const load: PageServerLoad = ({ params, locals, url }) =>
  withApiResponseErrorHandling(
    async () => {
      const requestedCycle = parseSelectedCycle(url.searchParams);
      const bundle = await fetchEntityDetailBundle(locals.api, {
        entityType: "person",
        id: params.id
      });

      if (requestedCycle !== undefined) {
        const personFinanceSections = fetchPersonCandidateFinanceSections(locals.api, {
          personId: params.id,
          cycle: requestedCycle
        });
        const personContributionInsights = fetchPersonContributionInsights(locals.api, {
          id: params.id,
          cycle: requestedCycle
        });
        const personTopDonors = fetchPersonTopDonors(locals.api, {
          id: params.id,
          cycle: requestedCycle
        });
        const personTopEmployers = fetchPersonTopEmployers(locals.api, {
          id: params.id,
          cycle: requestedCycle
        });
        guardUnhandledRejection(personFinanceSections);
        guardUnhandledRejection(personContributionInsights);
        guardUnhandledRejection(personTopDonors);
        guardUnhandledRejection(personTopEmployers);

        return {
          ...bundle,
          personFinanceSections,
          personContributionInsights: Promise.resolve(await personContributionInsights),
          personTopDonors,
          personTopEmployers
        };
      }

      const personContributionInsights = fetchPersonContributionInsights(locals.api, {
        id: params.id
      });
      const selectedCycle = personContributionInsights.then(
        (contributionInsights) => contributionInsights.metadata.selected_cycle
      );
      const personFinanceSections = selectedCycle.then((cycle) =>
        fetchPersonCandidateFinanceSections(locals.api, {
          personId: params.id,
          cycle
        })
      );
      const personTopDonors = selectedCycle.then((cycle) =>
        fetchPersonTopDonors(locals.api, {
          id: params.id,
          cycle
        })
      );
      const personTopEmployers = selectedCycle.then((cycle) =>
        fetchPersonTopEmployers(locals.api, {
          id: params.id,
          cycle
        })
      );
      guardUnhandledRejection(personContributionInsights);
      guardUnhandledRejection(personFinanceSections);
      guardUnhandledRejection(personTopDonors);
      guardUnhandledRejection(personTopEmployers);

      return {
        ...bundle,
        personFinanceSections,
        personContributionInsights,
        personTopDonors,
        personTopEmployers
      };
    },
    "Backend person detail request failed."
  );
