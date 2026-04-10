/** Loads the search page and preserves backend validation as the source of truth. */
import { filterRenderableSearchResults, isSearchEntityType } from '$lib/search/contract';
import { withApiResponseErrorHandling } from '$lib/server/api/error';
import { fetchSearchResults } from '$lib/server/api/search';
import type { PageServerLoad } from './$types';

/** Returns empty state for untouched routes, otherwise fetches filtered search results. */
export const load: PageServerLoad = async ({ url, locals }) => {
  const hasQueryParam = url.searchParams.has('q');
  const query = url.searchParams.get('q') ?? '';
  const entityType = url.searchParams.get('entity_type') ?? '';

  // Treat only a truly blank route state as empty. If q is present in the URL,
  // even as an empty string, forward it so backend validation stays authoritative.
  if (!hasQueryParam && (entityType === '' || isSearchEntityType(entityType))) {
    return {
      query,
      entityType,
      results: []
    };
  }

  const results = await withApiResponseErrorHandling(
    () =>
      fetchSearchResults(locals.api, {
        q: query,
        entityType
      }),
    'Backend search request failed.'
  );

  return {
    query,
    entityType,
    results: filterRenderableSearchResults(results)
  };
};
