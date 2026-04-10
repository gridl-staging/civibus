/** Adapts backend API failures into route-friendly SvelteKit errors. */
import { error } from '@sveltejs/kit';
import { getApiErrorDisplayMessage } from '$lib/api/error-display';
import { ApiResponseError } from './client';

export { getApiErrorDisplayMessage };

/**
 * Re-throws backend API failures as SvelteKit HttpErrors while preserving
 * backend-owned payload details when available.
 */
export function throwApiResponseError(cause: ApiResponseError, fallbackMessage: string): never {
  if (typeof cause.body === 'string') {
    throw error(cause.status, cause.body);
  }

  if (cause.body && typeof cause.body === 'object') {
    throw error(cause.status, cause.body as App.Error);
  }

  throw error(cause.status, fallbackMessage);
}

export async function withApiResponseErrorHandling<T>(
  operation: () => Promise<T>,
  fallbackMessage: string
): Promise<T> {
  try {
    return await operation();
  } catch (cause) {
    if (cause instanceof ApiResponseError) {
      throwApiResponseError(cause, fallbackMessage);
    }

    throw cause;
  }
}
