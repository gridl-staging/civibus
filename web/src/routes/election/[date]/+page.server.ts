import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchElectionDateAggregate } from "$lib/server/api/civic-detail";
import { error } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

const ELECTION_CACHE_CONTROL = "public, max-age=120, s-maxage=120, stale-while-revalidate=60";
const INVALID_ELECTION_DATE_ERROR = {
  message: "Invalid election date.",
  detail: "Election date must be a real calendar date in YYYY-MM-DD format."
};

function isCanonicalCalendarDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }

  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export const load: PageServerLoad = ({ params, locals, setHeaders }) =>
  withApiResponseErrorHandling(async () => {
    if (!isCanonicalCalendarDate(params.date)) {
      throw error(400, INVALID_ELECTION_DATE_ERROR);
    }

    const electionAggregate = await fetchElectionDateAggregate(locals.api, { date: params.date });
    setHeaders({ "cache-control": ELECTION_CACHE_CONTROL });
    return electionAggregate;
  }, "Backend election aggregate request failed.");
