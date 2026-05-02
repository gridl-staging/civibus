import { fetchCoverageRegistry } from "$lib/server/api/metadata";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import type { PageServerLoad } from "./$types";

const COVERAGE_CACHE_CONTROL = "public, max-age=300, s-maxage=300, stale-while-revalidate=60";

export const load: PageServerLoad = ({ locals, setHeaders }) =>
  withApiResponseErrorHandling(async () => {
    setHeaders({ "cache-control": COVERAGE_CACHE_CONTROL });
    const coverageRows = await fetchCoverageRegistry(locals.api);
    return { coverageRows };
  }, "Backend coverage registry request failed.");
