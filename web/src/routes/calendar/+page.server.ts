import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchUpcomingElectionTimeline } from "$lib/server/api/civic-detail";
import type { PageServerLoad } from "./$types";

const CALENDAR_CACHE_CONTROL = "public, max-age=300, s-maxage=300, stale-while-revalidate=60";

export const load: PageServerLoad = ({ locals, setHeaders }) =>
  withApiResponseErrorHandling(async () => {
    setHeaders({ "cache-control": CALENDAR_CACHE_CONTROL });
    const timelineEntries = await fetchUpcomingElectionTimeline(locals.api);
    return { timelineEntries };
  }, "Backend election timeline request failed.");
