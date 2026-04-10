const API_BASE_URL_ENV_VAR = 'CIVIBUS_API_BASE_URL';
const API_KEY_ENV_VAR = 'CIVIBUS_API_KEY';

export type ApiEnvironment = Record<string, string | undefined>;

function parseConfiguredUrl(value: string): URL {
  try {
    return new URL(value);
  } catch {
    throw new Error(
      `Invalid backend base URL in ${API_BASE_URL_ENV_VAR}: "${value}". Expected an absolute http(s) URL.`
    );
  }
}

export function getApiBaseUrl(environment: ApiEnvironment = process.env): string {
  const configuredValue = environment[API_BASE_URL_ENV_VAR]?.trim();
  if (!configuredValue) {
    throw new Error(`Missing required environment variable: ${API_BASE_URL_ENV_VAR}`);
  }

  const parsedUrl = parseConfiguredUrl(configuredValue);
  if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
    throw new Error(
      `Invalid backend base URL in ${API_BASE_URL_ENV_VAR}: protocol must be http or https.`
    );
  }

  return parsedUrl.origin;
}

export function getApiRequestHeaders(environment: ApiEnvironment = process.env): HeadersInit {
  const configuredApiKey = environment[API_KEY_ENV_VAR]?.trim();
  if (!configuredApiKey) {
    return {};
  }

  return { 'X-API-Key': configuredApiKey };
}
