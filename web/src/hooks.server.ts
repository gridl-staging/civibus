import { createApiClient } from '$lib/server/api/client';
import { getApiBaseUrl, getApiRequestHeaders } from '$lib/server/api/config';
import type { Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
  event.locals.api = createApiClient({
    baseUrl: getApiBaseUrl,
    defaultHeaders: getApiRequestHeaders,
    fetch: event.fetch
  });

  return resolve(event);
};
