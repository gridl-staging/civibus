/** Shared frontend API client utilities for relative `/v1/*` requests. */
type ApiFetch = (input: URL | RequestInfo, init?: RequestInit) => Promise<Response>;
const RELATIVE_API_ORIGIN = 'https://civibus.invalid';
type ApiBaseUrlSource = string | (() => string);
type ApiDefaultHeadersSource = HeadersInit | (() => HeadersInit | undefined);
const DOT_SEGMENT_PATTERN = /(^|\/)\.{1,2}(?:\/|$)/;

export class ApiResponseError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`Backend request failed with status ${status}`);
    this.name = 'ApiResponseError';
    this.status = status;
    this.body = body;
  }
}

/** Rejects absolute URLs and non-`/v1` paths before they reach fetch. */
function ensureRelativeV1Path(path: string): void {
  if (!path.startsWith('/')) {
    throw new Error('requestJson requires a relative /v1 path.');
  }

  if (/^https?:\/\//i.test(path)) {
    throw new Error('requestJson requires a relative /v1 path, not an absolute URL.');
  }

  const [rawPathname] = path.split(/[?#]/, 1);
  const decodedPathname = decodeURIComponent(rawPathname);
  if (DOT_SEGMENT_PATTERN.test(decodedPathname)) {
    throw new Error('requestJson requires a relative /v1 path.');
  }

  const parsedPath = new URL(path, RELATIVE_API_ORIGIN);
  if (parsedPath.origin !== RELATIVE_API_ORIGIN) {
    throw new Error('requestJson requires a relative /v1 path, not an absolute URL.');
  }

  if (parsedPath.pathname !== '/v1' && !parsedPath.pathname.startsWith('/v1/')) {
    throw new Error('requestJson requires a relative /v1 path.');
  }
}

function toRequestUrl(baseUrl: string, path: string): string {
  return new URL(path, `${baseUrl}/`).toString();
}

function mergeHeaders(defaultHeaders?: HeadersInit, init?: RequestInit): RequestInit | undefined {
  if (!defaultHeaders) {
    return init;
  }

  const mergedHeaders = new Headers(defaultHeaders);
  const initHeaders = init?.headers;
  if (initHeaders) {
    for (const [key, value] of new Headers(initHeaders).entries()) {
      mergedHeaders.set(key, value);
    }
  }

  return { ...init, headers: mergedHeaders };
}

/** Parses JSON responses first, then falls back to text or `null` for empty bodies. */
async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';

  if (contentType.includes('application/json')) {
    return response.json();
  }

  const text = await response.text();
  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export type RequestJsonOptions = {
  baseUrl: ApiBaseUrlSource;
  defaultHeaders?: ApiDefaultHeadersSource;
  fetch: ApiFetch;
  path: string;
  init?: RequestInit;
};

/** Performs a validated backend request and throws `ApiResponseError` on failure. */
export async function requestJson<T>({
  baseUrl,
  defaultHeaders,
  fetch,
  path,
  init
}: RequestJsonOptions): Promise<T> {
  ensureRelativeV1Path(path);
  const resolvedBaseUrl = typeof baseUrl === 'function' ? baseUrl() : baseUrl;
  const resolvedDefaultHeaders =
    typeof defaultHeaders === 'function' ? defaultHeaders() : defaultHeaders;
  const mergedInit = mergeHeaders(resolvedDefaultHeaders, init);

  const response = await fetch(toRequestUrl(resolvedBaseUrl, path), mergedInit);
  const body = await parseResponseBody(response);

  if (!response.ok) {
    throw new ApiResponseError(response.status, body);
  }

  return body as T;
}

export type ApiClient = { requestJson<T>(path: string, init?: RequestInit): Promise<T> };

export function createApiClient(options: {
  baseUrl: ApiBaseUrlSource;
  defaultHeaders?: ApiDefaultHeadersSource;
  fetch: ApiFetch;
}): ApiClient {
  const { baseUrl, defaultHeaders, fetch } = options;

  return {
    requestJson<T>(path: string, init?: RequestInit): Promise<T> {
      return requestJson<T>({ baseUrl, defaultHeaders, fetch, path, init });
    }
  };
}
