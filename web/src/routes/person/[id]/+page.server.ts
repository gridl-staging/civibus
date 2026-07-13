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
import type { PageServerLoad } from "./$types";

function guardUnhandledRejection(promise: Promise<unknown>): void {
  void promise.catch(() => {});
}

/**
 */
export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(
    async () => {
      const bundle = await fetchEntityDetailBundle(locals.api, {
        entityType: "person",
        id: params.id
      });
      const personFinanceSections = fetchPersonCandidateFinanceSections(locals.api, {
        personId: params.id
      });
      const personContributionInsights = fetchPersonContributionInsights(locals.api, {
        id: params.id
      });
      const personTopDonors = fetchPersonTopDonors(locals.api, {
        id: params.id
      });
      const personTopEmployers = fetchPersonTopEmployers(locals.api, {
        id: params.id
      });
      guardUnhandledRejection(personFinanceSections);
      guardUnhandledRejection(personContributionInsights);
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
