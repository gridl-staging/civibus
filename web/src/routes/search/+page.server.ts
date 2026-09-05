/** Loads the search page and preserves backend validation as the source of truth. */
import { fail, redirect } from '@sveltejs/kit';
import {
  SEARCH_PAGE_SIZE,
  SEARCH_REGION_FILTER_TYPE,
  buildSearchPagePath,
  filterRenderableSearchResults,
  isSearchFilterType
} from '$lib/search/contract';
import { ApiResponseError } from '$lib/server/api/client';
import { getApiErrorDisplayMessage, throwApiResponseError } from '$lib/server/api/error';
import { fetchSearchResults } from '$lib/server/api/search';
import { fetchRegionalNavigationSearch } from '$lib/server/api/state-pages';
import type { Actions, PageServerLoad } from './$types';

const UNSAFE_SEARCH_OFFSET_MESSAGE =
  'The requested search page is too large to navigate safely. Submit the search to return to the first page.';

function readFormValueAsString(formData: FormData, key: string): string {
  const rawValue = formData.get(key);
  return typeof rawValue === 'string' ? rawValue : '';
}

function getSearchValidationMessage(errorBody: unknown): string {
  if (typeof errorBody === 'string') {
    return errorBody;
  }

  if (errorBody && typeof errorBody === 'object') {
    return getApiErrorDisplayMessage(errorBody as App.Error);
  }

  return 'The search request could not be validated. Review your query and try again.';
}

/**
 * Interprets the offset the backend just accepted as a page position.
 *
 * Only called after a successful response, so the backend remains authoritative
 * for accepted signed-bigint values. This guard owns the narrower JavaScript
 * range needed for exact labels and Previous/Next arithmetic.
 */
function readAcceptedOffset(rawOffset: string | null, resultCount: number): number | null {
  const parsedOffset = Number(rawOffset ?? '0');
  const forwardStep = Math.max(SEARCH_PAGE_SIZE, resultCount);

  if (
    parsedOffset < 0 ||
    !Number.isSafeInteger(parsedOffset) ||
    !Number.isSafeInteger(parsedOffset + forwardStep)
  ) {
    return null;
  }

  return parsedOffset;
}

/** Returns empty state for untouched routes, otherwise fetches filtered search results. */
export const load: PageServerLoad = async ({ url, locals }) => {
  const hasQueryParam = url.searchParams.has('q');
  const query = url.searchParams.get('q') ?? '';
  const entityType = url.searchParams.get('entity_type') ?? '';
  const rawOffset = url.searchParams.get('offset');

  // Treat only a truly blank route state as empty. If q is present in the URL,
  // even as an empty string, forward it so backend validation stays authoritative.
  if (!hasQueryParam && (entityType === '' || isSearchFilterType(entityType))) {
    return {
      query,
      entityType,
      offset: 0,
      hasNext: false,
      results: []
    };
  }

  if (entityType === SEARCH_REGION_FILTER_TYPE && rawOffset !== null) {
    throw redirect(
      308,
      buildSearchPagePath({ q: query, entityType: SEARCH_REGION_FILTER_TYPE })
    );
  }

  try {
    const regionOnly = entityType === SEARCH_REGION_FILTER_TYPE;
    const includeRegionalResults =
      regionOnly || (entityType === '' && (rawOffset === null || rawOffset === '0'));
    const [searchResponse, regionalResponse] = await Promise.all([
      regionOnly
        ? Promise.resolve({ items: [], has_next: false })
        : fetchSearchResults(locals.api, {
            q: query,
            entityType,
            limit: SEARCH_PAGE_SIZE,
            offset: rawOffset
          }),
      includeRegionalResults ? fetchRegionalNavigationSearch(locals.api, query) : null
    ]);
    const results = filterRenderableSearchResults(searchResponse.items);
    const hasUnrenderableResults = results.length !== searchResponse.items.length;
    const acceptedOffset = readAcceptedOffset(rawOffset, results.length);

    if (acceptedOffset === null) {
      return {
        query,
        entityType,
        offset: 0,
        hasNext: false,
        results: [],
        hasUnavailableResultPage: true,
        validationMessage: UNSAFE_SEARCH_OFFSET_MESSAGE
      };
    }

    return {
      query,
      entityType,
      offset: acceptedOffset,
      hasNext: searchResponse.has_next,
      ...(hasUnrenderableResults ? { hasUnrenderableResults: true } : {}),
      ...(regionalResponse !== null && regionalResponse.items.length > 0
        ? { regionalResults: regionalResponse.items }
        : {}),
      ...(regionalResponse !== null && regionalResponse.incomplete_node_kinds.length > 0
        ? { regionalIncompleteNodeKinds: regionalResponse.incomplete_node_kinds }
        : {}),
      ...(regionalResponse?.has_unsafe_omissions === true
        ? { regionalHasUnsafeOmissions: true }
        : {}),
      results
    };
  } catch (cause) {
    // Search treats backend 422 as user-correctable inline validation instead of a route error.
    if (cause instanceof ApiResponseError && cause.status === 422) {
      return {
        query,
        entityType,
        offset: 0,
        hasNext: false,
        results: [],
        validationMessage: getSearchValidationMessage(cause.body)
      };
    }

    if (cause instanceof ApiResponseError) {
      throwApiResponseError(cause, 'Backend search request failed.');
    }

    throw cause;
  }
};

export const actions: Actions = {
  default: async ({ request, locals }) => {
    const formData = await request.formData();
    const query = readFormValueAsString(formData, 'q');
    const entityType = readFormValueAsString(formData, 'entity_type');

    try {
      if (entityType === SEARCH_REGION_FILTER_TYPE) {
        await fetchRegionalNavigationSearch(locals.api, query);
      } else {
        await fetchSearchResults(locals.api, {
          q: query,
          entityType
        });
      }
    } catch (cause) {
      if (cause instanceof ApiResponseError && cause.status === 422) {
        return fail(422, {
          query,
          entityType,
          validationMessage: getSearchValidationMessage(cause.body)
        });
      }

      if (cause instanceof ApiResponseError) {
        throwApiResponseError(cause, 'Backend search request failed.');
      }

      throw cause;
    }

    throw redirect(
      303,
      buildSearchPagePath({
        q: query,
        entityType
      })
    );
  }
};
