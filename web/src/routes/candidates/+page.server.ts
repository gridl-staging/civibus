import { fetchCandidateList, type CandidateListRequest } from "$lib/server/api/campaign-finance-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { readOptionalQueryParams } from "$lib/server/query-params";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ url, locals }) =>
  withApiResponseErrorHandling(async () => {
    const queryParams = readOptionalQueryParams(url.searchParams, [
      "name",
      "state",
      "office",
      "sort",
      "offset",
      "limit"
    ] as const);
    const request: CandidateListRequest = {
      ...queryParams,
      // A blank name submit means "no name filter" (civibus-frq), matching the
      // blank-select convention below rather than sending an empty token.
      name: queryParams.name === "" ? undefined : queryParams.name,
      state: queryParams.state === "" ? undefined : queryParams.state,
      office: queryParams.office === "" ? undefined : queryParams.office,
      // A blank sort submit means "default", so drop it rather than sending an
      // empty token. Non-blank values pass through untouched: the backend owns
      // the closed sort vocabulary and falls back to the default for anything
      // it does not recognize.
      sort: queryParams.sort === "" ? undefined : queryParams.sort
    };

    // The browse page deliberately does not set include_unsafe_identity, so the
    // backend applies its default identity suppression. Suppressed candidates
    // stay reachable at their own /candidate/... routes.
    return fetchCandidateList(locals.api, request);
  }, "Backend candidate list request failed.");
