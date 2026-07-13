import { fetchCommitteeList, type CommitteeListRequest } from "$lib/server/api/campaign-finance-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { readOptionalQueryParams } from "$lib/server/query-params";
import type { PageServerLoad } from "./$types";

/**
 */
export const load: PageServerLoad = ({ url, locals }) =>
  withApiResponseErrorHandling(async () => {
    const request: CommitteeListRequest = readOptionalQueryParams(url.searchParams, [
      "state",
      "committee_type",
      "offset",
      "limit"
    ] as const);

    return fetchCommitteeList(locals.api, request);
  }, "Backend committee list request failed.");
