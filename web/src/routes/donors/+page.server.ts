import {
  hasDonorShortNameQueryGuidance,
  type DonorSearchByMode,
  type DonorSearchResponse
} from '$lib/donors/contract';
import { ApiResponseError } from '$lib/server/api/client';
import { throwApiResponseError } from '$lib/server/api/error';
import { fetchDonorSearch } from '$lib/server/api/donor-search';
import type { PageServerLoad } from './$types';

const DEFAULT_DONOR_SEARCH_BY: DonorSearchByMode = 'name';
const DEFAULT_DONOR_SEARCH_LIMIT = 20;
const DEFAULT_DONOR_SEARCH_OFFSET = 0;
const DONOR_UNSUPPORTED_BY_MESSAGE = 'Choose a search mode: name, employer, or ZIP.';
const DONOR_SHORT_QUERY_MESSAGE = 'Enter at least 3 characters to search by name or employer.';
const DONOR_ZIP_QUERY_MESSAGE = 'Enter a 5-digit ZIP or ZIP+4 to search by ZIP.';
const DONOR_VALIDATION_FALLBACK_MESSAGE =
  'The donor search request could not be validated. Review your query and try again.';

type DonorPageData = Omit<DonorSearchResponse, 'by'> & {
  by: string;
  validationMessage?: string;
  shortQueryGuidance?: boolean;
};

function readIntegerParam(searchParams: URLSearchParams, key: string, fallback: number): number {
  const rawValue = searchParams.get(key);
  if (rawValue === null || rawValue.trim() === '') {
    return fallback;
  }

  const parsedValue = Number.parseInt(rawValue, 10);
  return Number.isNaN(parsedValue) ? fallback : parsedValue;
}

function readDonorRouteParams(url: URL): Pick<DonorPageData, 'query' | 'by' | 'limit' | 'offset'> {
  return {
    query: url.searchParams.get('q') ?? '',
    by: url.searchParams.get('by') ?? DEFAULT_DONOR_SEARCH_BY,
    limit: readIntegerParam(url.searchParams, 'limit', DEFAULT_DONOR_SEARCH_LIMIT),
    offset: readIntegerParam(url.searchParams, 'offset', DEFAULT_DONOR_SEARCH_OFFSET)
  };
}

function emptyDonorPageData(
  params: Pick<DonorPageData, 'query' | 'by' | 'limit' | 'offset'>,
  extra: Pick<DonorPageData, 'validationMessage' | 'shortQueryGuidance'> = {}
): DonorPageData {
  return {
    ...params,
    results: [],
    ...extra
  };
}

function readFastApiDetail(errorBody: unknown): string | null {
  if (!errorBody || typeof errorBody !== 'object' || !('detail' in errorBody)) {
    return null;
  }

  const detail = (errorBody as { detail: unknown }).detail;
  return typeof detail === 'string' ? detail : null;
}

/**
 */
function getDonorValidationMessage(errorBody: unknown): string {
  const detail = readFastApiDetail(errorBody);

  if (detail?.startsWith('Unsupported donor search mode')) {
    return DONOR_UNSUPPORTED_BY_MESSAGE;
  }

  if (detail?.endsWith('require at least 3 characters')) {
    return DONOR_SHORT_QUERY_MESSAGE;
  }

  if (detail?.startsWith('Donor ZIP searches')) {
    return DONOR_ZIP_QUERY_MESSAGE;
  }

  return DONOR_VALIDATION_FALLBACK_MESSAGE;
}

export const load = (async ({ url, locals }): Promise<DonorPageData> => {
  const params = readDonorRouteParams(url);

  if (params.query.trim() === '') {
    return emptyDonorPageData({
      ...params,
      query: ''
    });
  }

  if (hasDonorShortNameQueryGuidance(params.query, params.by)) {
    return emptyDonorPageData(params, {
      shortQueryGuidance: true
    });
  }

  try {
    return await fetchDonorSearch(locals.api, {
      q: params.query,
      by: params.by,
      limit: params.limit,
      offset: params.offset
    });
  } catch (cause) {
    if (cause instanceof ApiResponseError && cause.status === 422) {
      return emptyDonorPageData(params, {
        validationMessage: getDonorValidationMessage(cause.body)
      });
    }

    if (cause instanceof ApiResponseError) {
      throwApiResponseError(cause, 'Donor search failed.');
    }

    throw cause;
  }
}) satisfies PageServerLoad<DonorPageData>;
