import { fetchCandidateList, type CandidateListRequest } from "$lib/server/api/campaign-finance-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { readOptionalQueryParams } from "$lib/server/query-params";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ url, locals }) =>
  withApiResponseErrorHandling(async () => {
    const queryParams = readOptionalQueryParams(url.searchParams, [
      "state",
      "office",
      "offset",
      "limit"
    ] as const);
    const request: CandidateListRequest = {
      ...queryParams,
      state: queryParams.state === "" ? undefined : queryParams.state,
      office: queryParams.office === "" ? undefined : queryParams.office
    };

    return fetchCandidateList(locals.api, request);
  }, "Backend candidate list request failed.");
