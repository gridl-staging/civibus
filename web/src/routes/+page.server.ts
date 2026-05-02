/** Loads the landing-page map by combining country geometry and state summaries in parallel. */
import { ApiResponseError } from "$lib/server/api/client";
import { throwApiResponseError } from "$lib/server/api/error";
import {
  fetchCountryGeometry,
  fetchStateCampaignFinanceSummaries
} from "$lib/server/api/state-pages";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async ({ locals }) => {
  try {
    const [geometry, stateSummaries] = await Promise.all([
      fetchCountryGeometry(locals.api),
      fetchStateCampaignFinanceSummaries(locals.api)
    ]);

    return { geometry, stateSummaries };
  } catch (cause) {
    if (cause instanceof ApiResponseError) {
      throwApiResponseError(cause, "Backend landing-page request failed.");
    }
    throw cause;
  }
};
