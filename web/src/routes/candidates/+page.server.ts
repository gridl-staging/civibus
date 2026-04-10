import { fetchCandidateList, type CandidateListRequest } from "$lib/server/api/campaign-finance-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { readOptionalQueryParams } from "$lib/server/query-params";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ url, locals }) =>
  withApiResponseErrorHandling(async () => {
    const request: CandidateListRequest = readOptionalQueryParams(url.searchParams, [
      "state",
      "office",
      "offset",
      "limit"
    ] as const);

    return fetchCandidateList(locals.api, request);
  }, "Backend candidate list request failed.");
