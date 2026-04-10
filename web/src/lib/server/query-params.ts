export function readOptionalQueryParam(searchParams: URLSearchParams, key: string): string | undefined {
  if (!searchParams.has(key)) {
    return undefined;
  }

  return searchParams.get(key) ?? "";
}

export function readOptionalQueryParams<const TKeys extends readonly string[]>(
  searchParams: URLSearchParams,
  keys: TKeys
): { [K in TKeys[number]]: string | undefined } {
  return Object.fromEntries(
    keys.map((key) => [key, readOptionalQueryParam(searchParams, key)])
  ) as { [K in TKeys[number]]: string | undefined };
}
