import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchElectionDateAggregate } from "$lib/server/api/civic-detail";
import type { PageServerLoad } from "./$types";

const ELECTION_CACHE_CONTROL = "public, max-age=120, s-maxage=120, stale-while-revalidate=60";

export const load: PageServerLoad = ({ params, locals, setHeaders }) =>
  withApiResponseErrorHandling(async () => {
    setHeaders({ "cache-control": ELECTION_CACHE_CONTROL });
    return fetchElectionDateAggregate(locals.api, { date: params.date });
  }, "Backend election aggregate request failed.");
