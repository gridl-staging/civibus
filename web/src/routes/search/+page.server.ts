/** Loads the search page and preserves backend validation as the source of truth. */
import { fail, redirect } from '@sveltejs/kit';
import { buildSearchPagePath, filterRenderableSearchResults, isSearchEntityType } from '$lib/search/contract';
import { ApiResponseError } from '$lib/server/api/client';
import { getApiErrorDisplayMessage, throwApiResponseError } from '$lib/server/api/error';
import { fetchSearchResults } from '$lib/server/api/search';
import type { Actions, PageServerLoad } from './$types';

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

  try {
    const results = await fetchSearchResults(locals.api, {
      q: query,
      entityType
    });

    return {
      query,
      entityType,
      results: filterRenderableSearchResults(results)
    };
  } catch (cause) {
    // Search treats backend 422 as user-correctable inline validation instead of a route error.
    if (cause instanceof ApiResponseError && cause.status === 422) {
      return {
        query,
        entityType,
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
      await fetchSearchResults(locals.api, {
        q: query,
        entityType
      });
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
