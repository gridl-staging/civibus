import { fetchDataSourcesMetadata } from "$lib/server/api/metadata";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import type { PageServerLoad } from "./$types";

const DATA_SOURCES_CACHE_CONTROL = "public, max-age=300, s-maxage=300, stale-while-revalidate=60";

export const load: PageServerLoad = ({ locals, setHeaders }) =>
  withApiResponseErrorHandling(async () => {
    setHeaders({ "cache-control": DATA_SOURCES_CACHE_CONTROL });
    const dataSources = await fetchDataSourcesMetadata(locals.api);
    return { dataSources };
  }, "Backend data-sources request failed.");
