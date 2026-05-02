import {
  fetchEntityDetailBundle,
  fetchPersonCivicHistorySections
} from "$lib/server/api/entity-detail";
import { fetchPersonCandidateFinanceSections } from "$lib/server/api/campaign-finance-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import type { PageServerLoad } from "./$types";

function guardUnhandledRejection(promise: Promise<unknown>): void {
  void promise.catch(() => {});
}

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(
    async () => {
      const bundle = await fetchEntityDetailBundle(locals.api, {
        entityType: "person",
        id: params.id
      });
      const personCivicHistory = bundle.relationships.then((relationships) =>
        fetchPersonCivicHistorySections(locals.api, relationships)
      );
      const personFinanceSections = fetchPersonCandidateFinanceSections(locals.api, {
        personId: params.id
      });
      guardUnhandledRejection(personCivicHistory);
      guardUnhandledRejection(personFinanceSections);

      return {
        ...bundle,
        personCivicHistory,
        personFinanceSections
      };
    },
    "Backend person detail request failed."
  );
