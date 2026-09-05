/**
 * @module Contest (race) detail route loader.
 *
 * Loads the contest record and the whole-race money scoreboard. Both come from
 * one backend call each, and the money call runs concurrently with the map
 * lookup, so page latency is the slower of the two rather than their sum.
 *
 * History worth keeping: this route used to fan out 4N+1 backend calls, one
 * bundle per candidacy, and measured 17.96s cold on a 21-candidacy Senate
 * contest with no cache-control at all. Worse, each candidacy's fetch was
 * wrapped in a bare `catch {}` that returned an empty section, so a backend
 * failure rendered as "data is not yet available" — indistinguishable from a
 * genuine data gap, which is how a real defect (an incumbent's money sitting on
 * a different person row) stayed hidden. Neither the fan-out nor the swallow
 * exists any more; a failed money fetch is now a visible failure.
 */
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchContestCandidateMoney, fetchContestDetail } from "$lib/server/api/civic-detail";
import { parseSelectedCycleQuery } from "$lib/server/selected_cycle_query";
import {
  createGeometryByLevelRecord,
  fetchOptionalCivicGeometry,
  toCivicGeometryLevel
} from "$lib/server/api/civic-geometry";
import type { PageServerLoad } from "./$types";

// Contest records and FEC money both change on a weekly refresh cadence at
// most, so a short shared-cache window costs nothing in freshness and removes
// the repeat-visit and crawler cost entirely. Matches /election/[date].
const CONTEST_CACHE_CONTROL = "public, max-age=120, s-maxage=120, stale-while-revalidate=60";

/**
 * Derive the campaign-finance cycle from the contest's election date.
 *
 * Used only when the request does not pin a cycle. Validates the date's
 * round-trip so a malformed election_date yields "no opinion" rather than a
 * plausible-looking wrong year; the backend then falls back to its own default.
 */
function parseElectionYearCycle(electionDate: string | null | undefined): number | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(electionDate ?? "");
  if (match === null) {
    return undefined;
  }

  const [, year, month, day] = match;
  const parsedDate = new Date(`${year}-${month}-${day}T00:00:00Z`);
  if (
    Number.isNaN(parsedDate.getTime()) ||
    parsedDate.getUTCFullYear() !== Number(year) ||
    parsedDate.getUTCMonth() + 1 !== Number(month) ||
    parsedDate.getUTCDate() !== Number(day)
  ) {
    return undefined;
  }

  return Number(year);
}

export const load: PageServerLoad = ({ params, locals, url, setHeaders }) =>
  withApiResponseErrorHandling(async () => {
    const requestedCycle = parseSelectedCycleQuery(url.searchParams);
    const contest = await fetchContestDetail(locals.api, { id: params.id });
    const selectedCycle = requestedCycle ?? parseElectionYearCycle(contest.election_date);
    const level = toCivicGeometryLevel(contest.electoral_division_type);
    const stateCode = contest.electoral_division_state?.toUpperCase() ?? null;
    const geometryByLevel = createGeometryByLevelRecord();

    // Geometry and money are independent of each other, so run them together: a
    // slow map lookup must not delay the scoreboard, and vice versa.
    const [geometry, contestCandidateMoney] = await Promise.all([
      level !== null && stateCode !== null
        ? fetchOptionalCivicGeometry(locals.api, { level, state: stateCode })
        : Promise.resolve(null),
      contest.candidacies.length === 0
        ? Promise.resolve(null)
        : fetchContestCandidateMoney(locals.api, { id: params.id, cycle: selectedCycle })
    ]);

    if (level !== null && geometry !== null) {
      geometryByLevel[level] = geometry;
    }

    setHeaders({ "cache-control": CONTEST_CACHE_CONTROL });
    return {
      contest,
      geometryByLevel,
      contestCandidateMoney,
      // The backend resolved and validated the cycle for every row in the
      // response, so it wins over whatever the client guessed from the date.
      contestSelectedCycle: contestCandidateMoney?.selected_cycle ?? selectedCycle ?? null
    };
  }, "Backend contest detail request failed.");
