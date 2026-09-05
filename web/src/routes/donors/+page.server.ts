import {
  assertDonorSearchResponse,
  hasDonorShortNameQueryGuidance,
  type DonorSearchByMode,
  type DonorSearchPathParams,
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
const UNAVAILABLE_DONOR_PAGE_MESSAGE =
  'The requested donor page could not be displayed safely. Submit the search to return to the first page.';

type DonorPageData = Omit<DonorSearchResponse, 'by' | 'rollup_completed_at'> & {
  by: string;
  rollup_completed_at: string | null;
  validationMessage?: string;
  shortQueryGuidance?: boolean;
};

type DonorPageParams = Pick<DonorPageData, 'query' | 'by' | 'limit' | 'offset'>;

type DonorIntegerParam = {
  requestValue: number | string;
  pageValue: number;
};

function readIntegerParam(
  searchParams: URLSearchParams,
  key: string,
  fallback: number
): DonorIntegerParam {
  const rawValue = searchParams.get(key);
  if (rawValue === null || rawValue.trim() === '') {
    return {
      requestValue: fallback,
      pageValue: fallback
    };
  }

  const parsedValue = Number(rawValue);
  return {
    // FastAPI owns lexical and bounds validation; this exact text is the request value.
    requestValue: rawValue,
    pageValue:
      /^[+-]?\d+$/.test(rawValue.trim()) && Number.isSafeInteger(parsedValue)
        ? parsedValue
        : fallback
  };
}

function readDonorRouteParams(url: URL): {
  pageParams: DonorPageParams;
  requestParams: DonorSearchPathParams;
} {
  const query = url.searchParams.get('q') ?? '';
  const by = url.searchParams.get('by') ?? DEFAULT_DONOR_SEARCH_BY;
  const limit = readIntegerParam(url.searchParams, 'limit', DEFAULT_DONOR_SEARCH_LIMIT);
  const offset = readIntegerParam(url.searchParams, 'offset', DEFAULT_DONOR_SEARCH_OFFSET);

  return {
    pageParams: {
      query,
      by,
      limit: limit.pageValue,
      offset: offset.pageValue
    },
    requestParams: {
      q: query,
      by,
      limit: limit.requestValue,
      offset: offset.requestValue
    }
  };
}

/** Keeps page labels and Previous/Next arithmetic inside JavaScript's exact range. */
function hasSafeDonorPagination(
  request: Pick<DonorSearchPathParams, 'limit' | 'offset'>,
  response: DonorSearchResponse
): boolean {
  const requestedLimit = Number(request.limit);
  const requestedOffset = Number(request.offset);
  const forwardStep = Math.max(requestedLimit, response.results.length);

  return (
    Number.isSafeInteger(requestedLimit) &&
    requestedLimit > 0 &&
    Number.isSafeInteger(requestedOffset) &&
    requestedOffset >= 0 &&
    Number.isSafeInteger(requestedOffset + forwardStep) &&
    response.limit === requestedLimit &&
    response.offset === requestedOffset
  );
}

function emptyDonorPageData(
  params: DonorPageParams,
  extra: Pick<DonorPageData, 'validationMessage' | 'shortQueryGuidance'> = {}
): DonorPageData {
  return {
    ...params,
    rollup_completed_at: null,
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
  const { pageParams, requestParams } = readDonorRouteParams(url);

  if (pageParams.query.trim() === '') {
    return emptyDonorPageData({
      ...pageParams,
      query: ''
    });
  }

  if (hasDonorShortNameQueryGuidance(pageParams.query, pageParams.by)) {
    return emptyDonorPageData(pageParams, {
      shortQueryGuidance: true
    });
  }

  try {
    const response = await fetchDonorSearch(locals.api, requestParams);
    assertDonorSearchResponse(response);

    if (!hasSafeDonorPagination(requestParams, response)) {
      return emptyDonorPageData(
        {
          ...pageParams,
          limit: DEFAULT_DONOR_SEARCH_LIMIT,
          offset: DEFAULT_DONOR_SEARCH_OFFSET
        },
        {
          validationMessage: UNAVAILABLE_DONOR_PAGE_MESSAGE
        }
      );
    }

    return response;
  } catch (cause) {
    if (cause instanceof ApiResponseError && cause.status === 422) {
      return emptyDonorPageData(pageParams, {
        validationMessage: getDonorValidationMessage(cause.body)
      });
    }

    if (cause instanceof ApiResponseError) {
      throwApiResponseError(cause, 'Donor search failed.');
    }

    throw cause;
  }
}) satisfies PageServerLoad<DonorPageData>;
