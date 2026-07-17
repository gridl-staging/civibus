import {
  fetchEntityDetailBundle
} from "$lib/server/api/entity-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { loadPersonMoneyBundle } from "$lib/server/api/person-money-bundle";
import { error } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

const INVALID_CYCLE_ERROR = {
  message: "Invalid cycle query parameter.",
  detail: "The cycle query parameter must be a single four-digit election cycle."
};

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
      const moneyBundle = requestedCycle === undefined
        ? loadPersonMoneyBundle(locals.api, params.id, {
            fallbackWhenBackendSelectedInsightsUnavailable: true
          })
        : await loadPersonMoneyBundle(locals.api, params.id, requestedCycle);

      return {
        ...bundle,
        ...moneyBundle
      };
    },
    "Backend person detail request failed."
  );
